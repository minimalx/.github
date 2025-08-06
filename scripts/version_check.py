#!/usr/bin/env python3

import json
import subprocess
import sys
import os
from pathlib import Path

VERSION_FILE = "version.json"

def load_version_from_file(path: Path):
    try:
        with open(path, "r") as f:
            data = json.load(f)
        return data["version"]
    except Exception as e:
        print(f"::error::Failed to read version from {path}: {e}")
        sys.exit(1)

def load_version_from_main():
    try:
        result = subprocess.run(
            ["git", "fetch", "origin", "main"],
            check=True,
            capture_output=True
        )

        raw_version = subprocess.run(
            ["git", "show", "origin/main:version.json"],
            check=True,
            capture_output=True,
            text=True
        ).stdout

        data = json.loads(raw_version)
        return data["version"]
    except subprocess.CalledProcessError as e:
        print(f"::error::Failed to retrieve version.json from main: {e.stderr}")
        sys.exit(1)
    except json.JSONDecodeError:
        print("::error::version.json on main branch is not valid JSON.")
        sys.exit(1)

def compare_versions(old, new):
    omj, omn, op = old["major"], old["minor"], old["patch"]
    nmj, nmn, np = new["major"], new["minor"], new["patch"]

    if nmj == omj + 1 and nmn == 0 and np == 0:
        return True  # valid major bump
    if nmj == omj and nmn == omn + 1 and np == 0:
        return True  # valid minor bump
    if nmj == omj and nmn == omn and np == op + 1:
        return True  # valid patch bump

    return False

def main():
    print("🔍 Checking version bump validity...")

    current_version = load_version_from_file(Path(VERSION_FILE))
    main_version = load_version_from_main()

    print(f"🔢 Current: {current_version}")
    print(f"🔢 Main:    {main_version}")

    if not compare_versions(main_version, current_version):
        print("::error::Invalid version bump. Only the following version increments are allowed:")
        print(f"         - Next major version: {main_version['major'] + 1}.0.0")
        print(f"         - Next minor version: {main_version['major']}.{main_version['minor'] + 1}.0")
        print(f"         - Next patch version: {main_version['major']}.{main_version['minor']}.{main_version['patch'] + 1}")
        print("         No other changes are allowed (e.g., skipping versions, reducing numbers, or multiple bumps at once).")
        sys.exit(1)

    print("✅ Valid version bump.")

    # If version is valid, emit tag for downstream jobs
    tag = f"Release_{current_version['major']}_{current_version['minor']}_{current_version['patch']}"

    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a") as f:
            f.write(f"version_tag={tag}\n")

    print(f"✅ Valid version bump. Outputting version tag: {tag}")

if __name__ == "__main__":
    main()
