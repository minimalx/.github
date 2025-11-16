#!/usr/bin/env python3
import os
import re
import sys
from pathlib import Path


SEMVER_REGEX = re.compile(r"([0-9]+\.[0-9]+\.[0-9][0-9A-Za-z.+-]*)")


def parse_version(raw_tag: str) -> str:
    """
    Extract the first semver-like token from the tag string.
    Mirrors the original sed-based extraction.
    """
    match = SEMVER_REGEX.search(raw_tag)
    if not match:
        raise ValueError(f"Could not parse version from tag: {raw_tag}")
    return match.group(1)


def append_to_github_env(env_vars: dict) -> None:
    """
    Append environment variables to the GITHUB_ENV file,
    so that subsequent steps in the job can use them.
    """
    github_env = os.environ.get("GITHUB_ENV")
    if not github_env:
        raise RuntimeError("GITHUB_ENV is not set; cannot export variables.")

    github_env_path = Path(github_env)
    with github_env_path.open("a", encoding="utf-8") as f:
        for key, value in env_vars.items():
            f.write(f"{key}={value}\n")


def main(argv: list[str]) -> int:
    if len(argv) != 4:
        print(
            "Usage: derive_metadata.py <tag> <package-name> <namespace>",
            file=sys.stderr,
        )
        return 1

    raw_tag, package_name, namespace = argv[1], argv[2], argv[3]

    if not namespace:
        print(
            "Namespace is required for CodeArtifact generic format.",
            file=sys.stderr,
        )
        return 1

    try:
        version = parse_version(raw_tag)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    filename = f"{package_name}-{version}.zip"

    env_vars = {
        "VERSION": version,
        "PACKAGE": package_name,
        "FILENAME": filename,
        "NAMESPACE": namespace,
    }

    append_to_github_env(env_vars)

    # Match the original log line
    print(
        f"Parsed VERSION={version}, PACKAGE={package_name}, "
        f"FILENAME={filename}, NAMESPACE={namespace}"
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
