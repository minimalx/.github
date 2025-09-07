#!/usr/bin/env python3
import os
import re
import subprocess
import sys
from pathlib import Path
from packaging.version import Version, InvalidVersion

# ------------------------
# Utilities
# ------------------------

import json

def aws(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["aws", *args], capture_output=True, text=True)

def list_dev_versions_from_codeartifact(
    domain: str, domain_owner: str, repository: str, package: str, region: str,
    base: Version
) -> list[Version]:
    """
    Returns all published v{base}.devN versions for the given package from CodeArtifact.
    Requires AWS credentials in env (role assumed in the job).
    """
    versions: list[Version] = []
    next_token = None
    while True:
        cmd = [
            "codeartifact", "list-package-versions",
            "--domain", domain,
            "--domain-owner", domain_owner,
            "--repository", repository,
            "--format", "pypi",
            "--package", package,
            "--status", "Published",
            "--region", region,
        ]
        if next_token:
            cmd += ["--next-token", next_token]
        out = aws(*cmd)
        if out.returncode != 0:
            # surface error for caller to decide on fallback
            raise RuntimeError(f"CodeArtifact list-package-versions failed: {out.stderr.strip()}")
        data = json.loads(out.stdout or "{}")
        print(data)
        for item in data.get("versions", []):
            ver = item.get("version")
            print(ver)
            if not ver:
                continue
            # Match base.devN exactly (PEP 440 ok)
            m = re.fullmatch(rf"{base.major}\.{base.minor}\.{base.micro}\.dev(\d+)", ver)
            if m:
                try:
                    versions.append(Version(ver))
                except InvalidVersion:
                    pass
        next_token = data.get("nextToken")
        if not next_token:
            break
    return versions

def next_dev_number_from_codeartifact(
    base: Version, package: str
) -> int | None:
    """
    Compute next devN by querying CodeArtifact DEV repo using env:
      AWS_REGION_CODEARTIFACT / AWS_DOMAIN / AWS_DEV_DOMAIN_OWNER / AWS_PYTHON_REPO_DEV
    Returns None if it can't query (no creds, CLI missing, or error).
    """
    domain = os.environ.get("AWS_DOMAIN")
    domain_owner = os.environ.get("AWS_DEV_DOMAIN_OWNER") or os.environ.get("AWS_DOMAIN_OWNER")
    repository = os.environ.get("AWS_PYTHON_REPO_DEV") or os.environ.get("REPO_DEV")
    region = os.environ.get("AWS_REGION_CODEARTIFACT") or os.environ.get("AWS_REGION")
    if not all([domain, domain_owner, repository, region]):
        return None
    try:
        versions = list_dev_versions_from_codeartifact(
            domain=domain,
            domain_owner=domain_owner,
            repository=repository,
            package=package,
            region=region,
            base=base,
        )
    except Exception:
        return None
    if not versions:
        return 0
    # pick max devN and add 1
    max_dev = max(v.dev for v in versions if v.is_prerelease and v.dev is not None)
    return int(max_dev) + 1 if max_dev is not None else 0

def resolve_repo_root() -> Path:
    ws = os.environ.get("GITHUB_WORKSPACE")
    if ws:
        return Path(ws).resolve()
    out = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True, text=True
    )
    if out.returncode == 0:
        return Path(out.stdout.strip()).resolve()
    here = Path(__file__).resolve().parent
    for p in [here] + list(here.parents):
        if (p / ".git").exists():
            return p
    return Path.cwd().resolve()

ROOT = resolve_repo_root()
SRC = ROOT / "src"

VERSION_RE = re.compile(r'^__version__\s*=\s*[\'"]([^\'"]+)[\'"]\s*$', re.M)
TAG_SEMVER_RE = re.compile(r"^v(\d+)\.(\d+)\.(\d+)(?:\.dev(\d+))?$")

def git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], capture_output=True, text=True)

def parse_version_from_text(text: str) -> Version:
    m = VERSION_RE.search(text)
    if not m:
        raise ValueError("Could not find __version__ = '...' in file")
    try:
        return Version(m.group(1).strip())
    except InvalidVersion as e:
        raise ValueError(f"Invalid version string: {m.group(1)!r}") from e

def read_pr_version(path: Path) -> Version:
    text = path.read_text(encoding="utf-8")
    return parse_version_from_text(text)

def list_semver_tags(merged_ref: str | None = None) -> list[tuple[str, Version]]:
    """
    Return [(tag_name, Version)] for tags matching vX.Y.Z[.devN].
    If merged_ref is provided, only include tags whose target commit is merged into that ref.
    """
    # Get all tags first (names)
    out = git("tag", "--list", "v*")
    if out.returncode != 0:
        return []
    tags = [t.strip() for t in out.stdout.splitlines() if t.strip()]
    if not tags:
        return []

    # If restricting to those merged into a ref, ask git for merged tags
    if merged_ref:
        merged = git("tag", "--merged", merged_ref)
        if merged.returncode == 0:
            merged_set = {t.strip() for t in merged.stdout.splitlines() if t.strip()}
            tags = [t for t in tags if t in merged_set]

    result: list[tuple[str, Version]] = []
    for t in tags:
        m = TAG_SEMVER_RE.fullmatch(t)
        if not m:
            continue
        major, minor, micro, dev = m.groups()
        if dev is None:
            v = Version(f"{int(major)}.{int(minor)}.{int(micro)}")
        else:
            v = Version(f"{int(major)}.{int(minor)}.{int(micro)}.dev{int(dev)}")
        result.append((t, v))
    return result

def latest_version_on_main(base_ref: str = "main") -> Version:
    """
    Determine the latest version (final or dev) reachable from origin/<base_ref>.
    If none exist, return 0.0.0.
    """
    # Ensure we have the base branch
    git("fetch", "origin", base_ref)
    merged_ref = f"origin/{base_ref}"
    tv = list_semver_tags(merged_ref=merged_ref)
    if not tv:
        return Version("0.0.0")
    # Choose the max by Version ordering (PEP 440: dev < final)
    return max((v for _, v in tv), default=Version("0.0.0"))

def has_final_tag_for_base(base: Version) -> bool:
    out = git("tag", "--list", f"v{base.major}.{base.minor}.{base.micro}")
    if out.returncode != 0:
        return False
    return any(t.strip() == f"v{base.major}.{base.minor}.{base.micro}" for t in out.stdout.splitlines())

def has_dev_tag_for_base(base: Version) -> bool:
    out = git("tag", "--list", f"v{base.major}.{base.minor}.{base.micro}.dev*")
    if out.returncode != 0:
        return False
    return any(
        re.fullmatch(rf"v{base.major}\.{base.minor}\.{base.micro}\.dev\d+", t.strip())
        for t in out.stdout.splitlines()
    )

def next_dev_number_for_base(base: Version, main_v: Version) -> int:
    """
    Next devN for base X.Y.Z by scanning tags vX.Y.Z.dev* and considering main_v if it is already a dev on the same base.
    """
    start = -1
    if main_v.is_prerelease and main_v.dev is not None:
        main_base = Version(f"{main_v.major}.{main_v.minor}.{main_v.micro}")
        if main_base == base:
            start = max(start, int(main_v.dev))
    out = git("tag", "--list", f"v{base.major}.{base.minor}.{base.micro}.dev*")
    if out.returncode == 0:
        for line in out.stdout.splitlines():
            line = line.strip()
            m = re.fullmatch(rf"v{base.major}\.{base.minor}\.{base.micro}\.dev(\d+)", line)
            if m:
                start = max(start, int(m.group(1)))
    return start + 1

def is_exact_one_step_base(base: Version, main_v: Version) -> bool:
    """
    True if 'base' (no dev) is exactly one of:
      - major: (main.major+1).0.0
      - minor: main.major.(main.minor+1).0
      - patch: main.major.main.minor.(main.micro+1)
    """
    main_base = Version(f"{main_v.major}.{main_v.minor}.{main_v.micro}")
    if base <= main_base:
        return False
    major_next = Version(f"{main_v.major + 1}.0.0")
    minor_next = Version(f"{main_v.major}.{main_v.minor + 1}.0")
    patch_next = Version(f"{main_v.major}.{main_v.minor}.{main_v.micro + 1}")
    return base in {major_next, minor_next, patch_next}

def find_package_inits(src_dir: Path):
    # collect src/*/__init__.py
    return sorted((p / "__init__.py") for p in src_dir.glob("*") if (p / "__init__.py").exists())

def detect_ci_context() -> tuple[bool, bool]:
    """
    Returns (is_pr, is_push_main)
    """
    event = os.environ.get("GITHUB_EVENT_NAME", "")
    ref = os.environ.get("GITHUB_REF", "")
    ref_name = os.environ.get("GITHUB_REF_NAME", "")
    is_pr = event.startswith("pull_request") or bool(os.environ.get("GITHUB_HEAD_REF"))
    is_push_main = (event == "push") and (ref == "refs/heads/main" or ref_name == "main")
    return is_pr, is_push_main

def write_github_output(tag: str):
    gh_output = os.environ.get("GITHUB_OUTPUT")
    if gh_output:
        with open(gh_output, "a", encoding="utf-8") as fh:
            fh.write(f"tag={tag}\n")

# ------------------------
# Main
# ------------------------

def main():
    base_ref = os.environ.get("GITHUB_BASE_REF") or "main"
    main_v = latest_version_on_main(base_ref)  # <-- derive from tags, not files

    package_inits = find_package_inits(SRC)
    if not package_inits:
        print("No packages found under src/*/__init__.py", file=sys.stderr)
        sys.exit(1)

    is_pr, is_push_main = detect_ci_context()

    failures = []
    rows = []  # (pkg, main_v, pr_v, ok, base_str)
    proposed_bases: set[Version] = set()

    for init_file in package_inits:
        pkg = init_file.parent.name
        try:
            pr_v = read_pr_version(init_file)
        except Exception as e:
            failures.append(f"[{pkg}] PR version read failed: {e}")
            continue

        proposed_base = Version(f"{pr_v.major}.{pr_v.minor}.{pr_v.micro}")
        main_base = Version(f"{main_v.major}.{main_v.minor}.{main_v.micro}")

        if is_pr:
            # PR rules vs tag-derived main_v
            if main_v.is_prerelease and main_v.dev is not None:
                ok = (proposed_base == main_base)
            elif proposed_base == main_base:
                # allow equal-base only if no final tag exists yet for this base
                ok = not has_final_tag_for_base(main_base)
            else:
                ok = is_exact_one_step_base(proposed_base, main_v)
            base_ok = proposed_base if ok else None
        else:
            # Merge-to-main rules vs tag-derived main_v
            if pr_v.is_prerelease and pr_v.dev is not None:
                ok = False
                base_ok = None
            else:
                bootstrap_finish = (
                    proposed_base == main_base
                    and has_dev_tag_for_base(proposed_base)
                    and not has_final_tag_for_base(proposed_base)
                )
                ok = (
                    (main_v.is_prerelease and main_v.dev is not None and proposed_base == main_base)
                    or is_exact_one_step_base(proposed_base, main_v)
                    or bootstrap_finish
                )
                base_ok = proposed_base if ok else None

        rows.append((pkg, str(main_v), str(pr_v), bool(ok), str(base_ok) if base_ok else "-"))
        if ok and base_ok:
            proposed_bases.add(base_ok)
        else:
            if is_pr:
                failures.append(
                    f"[{pkg}] Invalid version relative to latest tag on main={main_v}: found {pr_v}. "
                    f"PRs may: (a) match main’s base if no final tag exists yet, "
                    f"(b) match main’s base if main has a dev on that base, or "
                    f"(c) bump exactly one step (major/minor/patch)."
                )
            else:
                failures.append(
                    f"[{pkg}] Invalid release version on merge: main(tag)={main_v}, found {pr_v}. "
                    f"Expected a plain release one-step from main, or finishing a dev cycle."
                )

    if proposed_bases:
        if len(proposed_bases) > 1:
            failures.append(
                "Multiple packages propose different base versions, which is not allowed: "
                + ", ".join(sorted(str(b) for b in proposed_bases))
            )
    else:
        pass

    if failures:
        print("Version check failed:\n" + "\n".join(failures), file=sys.stderr)
        print("\nObserved versions:", file=sys.stderr)
        for pkg, main_v_s, pr_v_s, ok, base in rows:
            print(f"  - {pkg}: main(tag)={main_v_s} pr={pr_v_s} base={base} ok={ok}", file=sys.stderr)
        sys.exit(1)

    # Agreed base
    base = next(iter(proposed_bases))

    if is_pr:
        # Prefer CodeArtifact (DEV) so we never collide with an already-published immutable version
        # Choose a representative package name (assumes single package; if multi, you can pick the first)
        primary_pkg = package_inits[0].parent.name
        devn = next_dev_number_from_codeartifact(base, primary_pkg)
        if devn is None:
            # Fallback to existing git-tag scan if CA is unavailable
            devn = next_dev_number_for_base(base, main_v)
        tag = f"v{base.major}.{base.minor}.{base.micro}.dev{devn}"
    else:
        tag = f"v{base.major}.{base.minor}.{base.micro}"

    write_github_output(tag)

    print("SemVer check passed for packages (using tags on main):")
    for pkg, main_v_s, pr_v_s, ok, base_str in rows:
        print(f"  - {pkg}: main(tag)={main_v_s} -> pr={pr_v_s} (base {base_str})")
    print(f"Tag: {tag}")

if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as e:
        print(f"Git error: {e}", file=sys.stderr)
        sys.exit(2)
