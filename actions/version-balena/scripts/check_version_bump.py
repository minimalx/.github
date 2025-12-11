#!/usr/bin/env python3
import argparse
import re
import subprocess
import sys
from typing import Optional, Tuple


VERSION_REGEX = re.compile(r"^version:\s*['\"]?(\d+\.\d+\.\d+)['\"]?\s*$")


def run_git_show(commit: str, path: str, allow_missing: bool = False) -> Optional[str]:
    try:
        output = subprocess.check_output(
            ["git", "show", f"{commit}:{path}"],
            stderr=subprocess.STDOUT,
            text=True,
        )
        return output
    except subprocess.CalledProcessError as e:
        msg = e.output.strip()

        # When the file doesn't exist in that commit, Git can say things like:
        #   fatal: path 'balena.yml' exists on disk, but not in '...sha...'
        # or:
        #   fatal: Path 'balena.yml' does not exist in '...sha...'
        if allow_missing and (
            "exists on disk, but not in" in msg
            or "does not exist in" in msg
            or "pathspec" in msg  # extra safety for other variants
        ):
            print(
                f"Base version file '{path}' does not exist at {commit}. "
                "Treating this as an initial version and skipping comparison."
            )
            return None

        print(f"::error::Failed to read {path} at {commit}: {msg}")
        sys.exit(1)


def extract_version_from_content(content: str) -> str:
    for line in content.splitlines():
        line = line.strip()
        match = VERSION_REGEX.match(line)
        if match:
            return match.group(1)

    print("::error::Could not find a valid `version:` line in balena.yml")
    sys.exit(1)


def parse_semver(version: str) -> Tuple[int, int, int]:
    semver_pattern = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
    match = semver_pattern.match(version)
    if not match:
        print(f"::error::Version '{version}' is not a valid semantic version (MAJOR.MINOR.PATCH).")
        sys.exit(1)
    return tuple(int(part) for part in match.groups())  # type: ignore[return-value]


def compare_versions(old: Tuple[int, int, int], new: Tuple[int, int, int]) -> int:
    """Return -1 if new < old, 0 if equal, 1 if new > old."""
    if new == old:
        return 0
    if new > old:
        return 1
    return -1


def print_bump_suggestions(base_ver: Tuple[int, int, int]) -> None:
    major, minor, patch = base_ver
    major_bump = f"{major + 1}.0.0"
    minor_bump = f"{major}.{minor + 1}.0"
    patch_bump = f"{major}.{minor}.{patch + 1}"

    print("Update version in balena.yml. Possible new versions are:")
    print(f"- MAJOR: {major_bump}")
    print(f"- MINOR: {minor_bump}")
    print(f"- PATCH: {patch_bump}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Check that balena.yml version has been bumped with semantic versioning."
    )
    parser.add_argument("--base", required=True, help="Base commit SHA to compare from")
    parser.add_argument("--head", required=True, help="Head commit SHA to compare to")
    parser.add_argument("--file", default="balena.yml", help="Path to balena.yml (default: balena.yml)")

    args = parser.parse_args()

    # Allow the base file to be missing (e.g., first introduction of balena.yml)
    base_content = run_git_show(args.base, args.file, allow_missing=True)
    head_content = run_git_show(args.head, args.file, allow_missing=False)

    if head_content is None:
        print(f"::error::Version file '{args.file}' is missing in the head commit.")
        sys.exit(1)

    head_version_str = extract_version_from_content(head_content)
    # Validate semver for head
    head_ver = parse_semver(head_version_str)

    # If base file doesn't exist, just validate semver (already done) and accept
    if base_content is None:
        print(
            f"No previous '{args.file}' found in base commit. "
            f"Treating '{head_version_str}' as initial version. Version bump check passed ✅"
        )
        # Emit machine-readable line for the GitHub Action
        print(f"VERSION_OUTPUT={head_version_str}")
        sys.exit(0)

    base_version_str = extract_version_from_content(base_content)
    base_ver = parse_semver(base_version_str)

    print(f"Base version: {base_version_str}")
    print(f"Head version: {head_version_str}")

    cmp_result = compare_versions(base_ver, head_ver)

    if cmp_result < 0:
        print("::error::Version in head is lower than version in base. Version must only increase.")
        print_bump_suggestions(base_ver)
        sys.exit(1)
    elif cmp_result == 0:
        print("::error::Version has not been bumped. Please increment the version in balena.yml.")
        print_bump_suggestions(base_ver)
        sys.exit(1)

    print("Version bump check passed ✅")
    # Emit machine-readable line for the GitHub Action
    print(f"VERSION_OUTPUT={head_version_str}")
    sys.exit(0)


if __name__ == "__main__":
    main()
