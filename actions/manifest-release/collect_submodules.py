#!/usr/bin/env python3
import subprocess
import re
from pathlib import Path

def run_git(args, cwd=None, check=True):
    """Run a git command and return stdout as string."""
    result = subprocess.run(
        ["git"] + args,
        cwd=cwd,
        text=True,
        capture_output=True,
        check=check,
    )
    return result.stdout.strip()

def main():
    root = Path.cwd()
    output_file = root / "submodule_versions.txt"

    print("::group::Submodule versions")

    # Truncate / create file
    output_file.write_text("", encoding="utf-8")

    # Read submodule paths from .gitmodules
    try:
        config_output = run_git(["config", "-f", ".gitmodules", "--get-regexp", "path"])
    except subprocess.CalledProcessError:
        print(".gitmodules not found or no submodules configured")
        print("::endgroup::")
        return

    paths = []
    for line in config_output.splitlines():
        parts = line.strip().split()
        if len(parts) >= 2:
            path = parts[1]
            if path == "workflow-templates":
                # Skip this one as in the original script
                continue
            paths.append(path)

    with output_file.open("w", encoding="utf-8") as f:
        for path in paths:
            print()
            print(f"### {path}")

            # Get commit SHAs
            commit_sha = run_git(["-C", path, "rev-parse", "HEAD"])
            short_sha = run_git(["-C", path, "rev-parse", "--short", "HEAD"])

            # Get tags pointing at HEAD, filter out tags containing "_BL_"
            try:
                tags_raw = run_git(["-C", path, "tag", "--points-at", "HEAD"])
                tags_list = [
                    t for t in tags_raw.splitlines()
                    if t and "_BL_" not in t
                ]
            except subprocess.CalledProcessError:
                tags_list = []

            version = ""

            if not tags_list:
                print("Tags:   (none pointing at commit after filtering)")
                # Try to find nearest tag
                try:
                    nearest = run_git(
                        ["-C", path, "describe", "--tags", "--always", "--dirty"],
                        check=False,
                    )
                except subprocess.CalledProcessError:
                    nearest = ""

                if nearest:
                    print(f"Nearest: {nearest}")
            else:
                print("Tags:")
                for t in tags_list:
                    print(f"  - {t}")

                first_tag = tags_list[0]
                match = re.search(r"[0-9]+\.[0-9]+\.[0-9]+", first_tag)
                if match:
                    version = match.group(0)
                else:
                    print(f"Warning: could not parse version from tag '{first_tag}'")
                    version = ""

            print(f"Commit: {short_sha} ({commit_sha})")

            # Write "<path> <version>" to submodule_versions.txt
            f.write(f"{path} {version}\n")

    print("::endgroup::")

if __name__ == "__main__":
    main()
