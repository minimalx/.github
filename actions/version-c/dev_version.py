#!/usr/bin/env python3
"""Give a development build a version that names exactly one commit.

A development build is X.Y.Z-devN, where X.Y.Z is the next release that
paulhatch/semantic-version computed and N counts the first-parent commits from
the newest reachable release tag to the built commit. Along develop's
first-parent line every commit gets a different N, so two builds of different
code can never share a version (the old ${increment} could).

It refuses, rather than guesses, when:
  * the history is shallow (N would be wrong);
  * a release at or above X.Y.Z exists but is not merged back into the built
    commit, so X.Y.Z-devN would sort below a release that is already out;
  * the built commit is itself a release (there is nothing to build as dev).

The output also carries dev_tag, dev/<prefix><version>. The dev/ namespace
keeps these tags out of every lookup of release tags (refs/tags/<prefix>*,
git describe --match '<prefix>*').
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

DEV_TAG_NAMESPACE = "dev/"
_BASE_RE = re.compile(r"(\d+)\.(\d+)\.(\d+)")


class DevVersionError(Exception):
    """The development version cannot be given safely."""


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def _parse(text: str) -> tuple[int, int, int]:
    match = _BASE_RE.fullmatch(text.strip())
    if match is None:
        raise DevVersionError(f"base version '{text}' is not X.Y.Z")
    return tuple(int(part) for part in match.groups())  # type: ignore[return-value]


def release_tags(repo: Path, prefix: str, merged: str | None = None) -> list[tuple[tuple[int, int, int], str]]:
    """Release tags <prefix>X.Y.Z, newest version first; only those reachable from
    merged when it is given. Anything with a suffix is not a release."""
    args = ["for-each-ref", "--format=%(refname:short)"]
    if merged is not None:
        args.append(f"--merged={merged}")
    args.append(f"refs/tags/{prefix}*")
    pattern = re.compile(re.escape(prefix) + r"(\d+)\.(\d+)\.(\d+)")
    found = []
    for line in _git(repo, *args).splitlines():
        tag = line.strip()
        match = pattern.fullmatch(tag)
        if match:
            found.append((tuple(int(part) for part in match.groups()), tag))
    return sorted(found, reverse=True)


def dev_version(repo: Path, prefix: str, base: str, commit: str = "HEAD") -> dict[str, str]:
    if _git(repo, "rev-parse", "--is-shallow-repository") == "true":
        raise DevVersionError(
            "the history is shallow: check out with fetch-depth: 0 so the build number is right"
        )
    head = _git(repo, "rev-parse", f"{commit}^{{commit}}")
    wanted = _parse(base)

    reachable = release_tags(repo, prefix, merged=head)
    reachable_names = {tag for _, tag in reachable}
    behind = [
        tag for version, tag in release_tags(repo, prefix)
        if version >= wanted and tag not in reachable_names
    ]
    if behind:
        raise DevVersionError(
            f"release {behind[0]} is not merged back into this branch, so "
            f"{base}-devN would sort below a release that is already out: "
            "merge main back into develop first"
        )

    if reachable:
        base_tag = reachable[0][1]
        if _git(repo, "rev-parse", f"{base_tag}^{{commit}}") == head:
            raise DevVersionError(f"{head[:12]} is the release {base_tag}, not a development build")
        build = int(_git(repo, "rev-list", "--first-parent", "--count", f"{base_tag}..{head}"))
    else:
        build = int(_git(repo, "rev-list", "--first-parent", "--count", head))

    version = f"{base}-dev{build}"
    return {
        "version": version,
        "version_tag": f"{prefix}{version}",
        "dev_tag": f"{DEV_TAG_NAMESPACE}{prefix}{version}",
        "build": str(build),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tag-prefix", required=True, help="such as BCU_APP_v")
    parser.add_argument("--base", required=True, help="X.Y.Z from semantic-version")
    parser.add_argument("--commit", default="HEAD")
    parser.add_argument("--repo", type=Path, default=Path("."))
    parser.add_argument("--github-output", action="store_true")
    args = parser.parse_args(argv)
    try:
        values = dev_version(args.repo, args.tag_prefix, args.base, args.commit)
    except (DevVersionError, subprocess.CalledProcessError) as error:
        detail = getattr(error, "stderr", "") or ""
        print(f"::error::dev version: {error} {detail}".strip(), file=sys.stderr)
        return 1
    lines = [f"{key}={value}" for key, value in values.items()]
    print("\n".join(lines))
    if args.github_output:
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
            output.write("\n".join(lines) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
