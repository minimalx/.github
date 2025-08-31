#!/usr/bin/env python3
import os
import re
import subprocess
import sys
from pathlib import Path
from packaging.version import Version, InvalidVersion

ROOT = Path(__file__).resolve().parents[2]  # repo root
SRC = ROOT / "src"

VERSION_RE = re.compile(r'^__version__\s*=\s*[\'"]([^\'"]+)[\'"]\s*$', re.M)

def git_show(path: Path, ref: str) -> str:
    """Return file content at a given git ref; raises on failure."""
    rel = path.relative_to(ROOT).as_posix()
    out = subprocess.run(["git", "show", f"{ref}:{rel}"], capture_output=True, text=True)
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

def is_allowed_next(pr_v: Version, main_v: Version) -> bool:
    """Enforce exactly-one-step semantics, including dev pre-releases."""
    if pr_v <= main_v:
        return False

    # If main is a dev, only allow bumping dev number on SAME base (A.B.C.devM -> A.B.C.dev(M+1))
    if main_v.is_prerelease and main_v.dev is not None:
        if (pr_v.release == main_v.release) and (pr_v.dev is not None) and (pr_v.dev == (main_v.dev + 1)):
            return True
        return False

    # Otherwise, main is a normal release. Accept exactly one of: patch+1, minor+1 reset patch, major+1 reset minor/patch
    major_next = Version(f"{main_v.major + 1}.0.0")
    minor_next = Version(f"{main_v.major}.{main_v.minor + 1}.0")
    patch_next = Version(f"{main_v.major}.{main_v.minor}.{main_v.micro + 1}")

    bases = {major_next, minor_next, patch_next}

    # Exact release of one of the bases
    if pr_v in bases:
        return True

    # Or a dev pre-release of exactly one of those bases (any non-negative devN)
    if pr_v.is_prerelease and pr_v.dev is not None:
        base_like = Version(f"{pr_v.major}.{pr_v.minor}.{pr_v.micro}")
        if base_like in bases and pr_v.dev >= 0:
            return True

    return False

def find_package_inits(src_dir: Path):
    return sorted(src_dir.glob("*/*"), key=lambda p: p.as_posix())  # ensure deterministic

def main():
    # Determine the "main" ref to compare with. Default to origin/main.
    base_ref = os.environ.get("GITHUB_BASE_REF") or "main"
    main_ref = f"origin/{base_ref}"

    # Make sure we have the remote base branch
    subprocess.run(["git", "fetch", "origin", base_ref], check=True)

    # Collect packages with __init__.py
    package_inits = sorted((p / "__init__.py") for p in SRC.glob("*") if (p / "__init__.py").exists())

    if not package_inits:
        print("No packages found under src/*/__init__.py", file=sys.stderr)
        sys.exit(1)

    failures = []
    results = []

    for init_file in package_inits:
        pkg_name = init_file.parent.name
        try:
            pr_v = read_pr_version(init_file)
        except Exception as e:
            failures.append(f"[{pkg_name}] PR version read failed: {e}")
            continue

        try:
            main_v = read_main_version(init_file, main_ref)
        except FileNotFoundError:
            # Package may be new—require it to start at 0.1.0 (or 0.1.0.devN). Adjust if you prefer a different rule.
            main_v = Version("0.0.0")
        except Exception as e:
            failures.append(f"[{pkg_name}] main version read failed: {e}")
            continue

        ok = is_allowed_next(pr_v, main_v)
        results.append((pkg_name, str(main_v), str(pr_v), ok))
        if not ok:
            failures.append(
                f"[{pkg_name}] Invalid bump: main={main_v} -> pr={pr_v}. "
                f"Allowed: major ({main_v.major+1}.0.0), minor ({main_v.major}.{main_v.minor+1}.0), "
                f"patch ({main_v.major}.{main_v.minor}.{main_v.micro+1}), or corresponding .devN; "
                f"if main is dev, only devN+1 is allowed."
            )

    # Enforce all packages agree on the final version string (common in monorepos); feel free to relax if unwanted
    pr_versions = {r[2] for r in results if r[3]}
    if len(pr_versions) > 1:
        failures.append(
            "Multiple packages have different PR versions, which is not allowed in this repo: "
            + ", ".join(sorted(pr_versions))
        )

    if failures:
        print("Version check failed:\n" + "\n".join(failures), file=sys.stderr)
        sys.exit(1)

    # Compute tag from the (single) PR version
    pr_version_str = pr_versions.pop()
    tag = f"v{pr_version_str}"

    # Export GitHub Action output
    gh_output = os.environ.get("GITHUB_OUTPUT")
    if gh_output:
        with open(gh_output, "a", encoding="utf-8") as fh:
            fh.write(f"tag={tag}\n")

    # Also print a small summary
    print("SemVer check passed for packages:")
    for pkg_name, main_v, pr_v, ok in results:
        print(f"  - {pkg_name}: {main_v} -> {pr_v}")
    print(f"Tag: {tag}")

if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as e:
        print(f"Git error: {e}", file=sys.stderr)
        sys.exit(2)
