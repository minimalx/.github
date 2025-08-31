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

def git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], capture_output=True, text=True)

def git_show(path: Path, ref: str) -> str:
    rel = path.relative_to(ROOT).as_posix()
    out = git("show", f"{ref}:{rel}")
    if out.returncode != 0:
        raise FileNotFoundError(f"Could not read {rel} at {ref}: {out.stderr.strip()}")
    return out.stdout

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

def read_main_version(path: Path, main_ref: str) -> Version:
    text = git_show(path, main_ref)
    return parse_version_from_text(text)

def is_exact_one_step_base(base: Version, main_v: Version) -> bool:
    """
    True if 'base' (no dev) is exactly one of:
      - major: (main.major+1).0.0
      - minor: main.major.(main.minor+1).0
      - patch: main.major.main.minor.(main.micro+1)
    """
    if base <= Version(f"{main_v.major}.{main_v.minor}.{main_v.micro}"):
        return False
    major_next = Version(f"{main_v.major + 1}.0.0")
    minor_next = Version(f"{main_v.major}.{main_v.minor + 1}.0")
    patch_next = Version(f"{main_v.major}.{main_v.minor}.{main_v.micro + 1}")
    return base in {major_next, minor_next, patch_next}

def find_package_inits(src_dir: Path):
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

def has_final_tag_for_base(base: Version) -> bool:
    """Does an exact final tag vX.Y.Z exist? (not a dev tag)"""
    out = git("tag", "--list", f"v{base.major}.{base.minor}.{base.micro}")
    if out.returncode != 0:
        return False
    return any(t.strip() == f"v{base.major}.{base.minor}.{base.micro}" for t in out.stdout.splitlines())

def next_dev_number_for_base(base: Version, main_v: Version) -> int:
    """
    Determine the next devN for the given base (X.Y.Z) by scanning git tags: vX.Y.Z.devN.
    If main itself is a dev prerelease on the same base, start from main.dev + 1.
    Otherwise, from the highest existing tag devN + 1, defaulting to 0.
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
            m = re.match(rf"^v{base.major}\.{base.minor}\.{base.micro}\.dev(\d+)$", line)
            if m:
                start = max(start, int(m.group(1)))
    return start + 1

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
    main_ref = f"origin/{base_ref}"

    # Ensure we have the base branch
    subprocess.run(["git", "fetch", "origin", base_ref], check=True)

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

        try:
            main_v = read_main_version(init_file, main_ref)
        except FileNotFoundError:
            # New package: pretend main base is 0.0.0, so 0.0.1 is a valid first step.
            main_v = Version("0.0.0")
        except Exception as e:
            failures.append(f"[{pkg}] main version read failed: {e}")
            continue

        proposed_base = Version(f"{pr_v.major}.{pr_v.minor}.{pr_v.micro}")
        main_base = Version(f"{main_v.major}.{main_v.minor}.{main_v.micro}")

        if is_pr:
            # --- PR behavior ---
            if main_v.is_prerelease and main_v.dev is not None:
                ok = (proposed_base == main_base)
            elif proposed_base == main_base:
                # Bootstrap / starting case (or pre-release work before first final tag):
                # allow equal base if there's no final tag for this base yet.
                ok = not has_final_tag_for_base(main_base)
            else:
                ok = is_exact_one_step_base(proposed_base, main_v)
            base_ok = proposed_base if ok else None
        else:
            # --- Merge to main ---
            if pr_v.is_prerelease and pr_v.dev is not None:
                ok = False
                base_ok = None
            else:
                # Either finish dev cycle (main was dev on same base) or one-step bump
                ok = (
                    (main_v.is_prerelease and main_v.dev is not None and proposed_base == main_base)
                    or is_exact_one_step_base(proposed_base, main_v)
                )
                base_ok = proposed_base if ok else None

        rows.append((pkg, str(main_v), str(pr_v), bool(ok), str(base_ok) if base_ok else "-"))
        if ok and base_ok:
            proposed_bases.add(base_ok)
        else:
            if is_pr:
                msg = (
                    f"[{pkg}] Invalid version proposal relative to main={main_v}: found {pr_v}. "
                    f"On PRs, allow: (a) same base as main if no final tag exists for that base, "
                    f"(b) same base if main is already a dev of that base, or "
                    f"(c) a one-step bump (major/minor/patch)."
                )
            else:
                msg = (
                    f"[{pkg}] Invalid release version on merge: main={main_v}, found {pr_v}. "
                    f"Expected a plain release that is one-step from main, or finishing a dev cycle."
                )
            failures.append(msg)

    # All packages must agree on a single base version
    if proposed_bases:
        if len(proposed_bases) > 1:
            failures.append(
                "Multiple packages propose different base versions, which is not allowed: "
                + ", ".join(sorted(str(b) for b in proposed_bases))
            )
    else:
        # No valid proposals collected
        pass

    if failures:
        print("Version check failed:\n" + "\n".join(failures), file=sys.stderr)
        print("\nObserved versions:", file=sys.stderr)
        for pkg, main_v, pr_v, ok, base in rows:
            print(f"  - {pkg}: main={main_v} pr={pr_v} base={base} ok={ok}", file=sys.stderr)
        sys.exit(1)

    # Single agreed base
    base = next(iter(proposed_bases))

    # Decide tag based on context
    if is_pr:
        any_main_v = Version(rows[0][1])
        devn = next_dev_number_for_base(base, any_main_v)
        tag = f"v{base.major}.{base.minor}.{base.micro}.dev{devn}"
    else:
        tag = f"v{base.major}.{base.minor}.{base.micro}"

    write_github_output(tag)

    print("SemVer check passed for packages:")
    for pkg, main_v, pr_v, ok, base_str in rows:
        print(f"  - {pkg}: main={main_v} -> pr={pr_v} (base {base_str})")
    print(f"Tag: {tag}")

if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as e:
        print(f"Git error: {e}", file=sys.stderr)
        sys.exit(2)
