#!/usr/bin/env python3
"""Version a development build of a balena app as X.Y.Z-devN.

X.Y.Z is the version in balena.yml: the superproject bumps it by hand in every
pull request, so on develop it already names the next release. N is the built
commit's first-parent depth, from version-c's dev_version.py, so every develop
merge gets its own, rising number and two builds of different code never share
a version. The same rules apply: a shallow history, a release tag at or above
X.Y.Z that the built commit does not contain, or a commit that is itself a
release all refuse rather than guess.

Outputs version (X.Y.Z-devN), version_tag (<prefix>X.Y.Z-devN), dev_tag
(dev/<prefix>X.Y.Z-devN) and build (N).
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "version-c"))

from dev_version import DevVersionError, dev_version  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))

from check_version_bump import VERSION_REGEX  # noqa: E402


def balena_version(repo: Path, commit: str, file: str) -> str:
    """The version: line of file at commit, X.Y.Z."""
    try:
        content = subprocess.run(
            ["git", "-C", str(repo), "show", f"{commit}:{file}"],
            check=True, capture_output=True, text=True,
        ).stdout
    except subprocess.CalledProcessError as error:
        raise DevVersionError(f"cannot read {file} at {commit}: {error.stderr.strip()}") from error
    for line in content.splitlines():
        match = VERSION_REGEX.match(line.strip())
        if match:
            return match.group(1)
    raise DevVersionError(f"{file} at {commit} has no 'version: X.Y.Z' line")


def dev_build(repo: Path, prefix: str, file: str = "balena.yml", commit: str = "HEAD") -> dict[str, str]:
    return dev_version(repo, prefix, balena_version(repo, commit, file), commit)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tag-prefix", required=True, help="such as TCU_STACK_v")
    parser.add_argument("--file", default="balena.yml")
    parser.add_argument("--commit", default="HEAD")
    parser.add_argument("--repo", type=Path, default=Path("."))
    parser.add_argument("--github-output", action="store_true")
    args = parser.parse_args(argv)
    try:
        values = dev_build(args.repo, args.tag_prefix, args.file, args.commit)
    except (DevVersionError, subprocess.CalledProcessError) as error:
        detail = getattr(error, "stderr", "") or ""
        print(f"::error::dev build version: {error} {detail}".strip(), file=sys.stderr)
        return 1
    lines = [f"{key}={value}" for key, value in values.items()]
    print("\n".join(lines))
    if args.github_output:
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
            output.write("\n".join(lines) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
