#!/usr/bin/env python3
"""
Print release notes comparing submodule tags between a base commit and HEAD.

For each submodule (except workflow-templates), this reports the tag pointing
to the submodule commit at the base commit and the tag pointing to the current
submodule commit. Tags containing "_BL_" are ignored for the main entry, and
bootloader tags are reported separately for selected submodules.
"""

import os
import subprocess
import sys
from typing import Dict, List, Optional

BOOTLOADER_TAG_PREFIXES = {
    "body-control-unit": "BCU_BL_v",
    "avas": "AVAS_BL_v",
    "security-module": "SM_BL_v",
}
BOOTLOADER_EXCLUDE_SUBSTRING = "_BL_"


def run_git(args, check: bool = True) -> str:
    """Run a git command and return stdout as a stripped string."""
    result = subprocess.run(
        ["git"] + args,
        text=True,
        capture_output=True,
    )
    if check and result.returncode != 0:
        raise subprocess.CalledProcessError(result.returncode, result.args, result.stdout, result.stderr)
    return result.stdout.strip()


def get_submodule_paths() -> List[str]:
    """Read submodule paths from .gitmodules, skipping workflow-templates."""
    try:
        config_output = run_git(["config", "-f", ".gitmodules", "--get-regexp", "path"])
    except subprocess.CalledProcessError:
        return []

    paths: List[str] = []
    for line in config_output.splitlines():
        parts = line.strip().split()
        if len(parts) >= 2:
            path = parts[1]
            if path == "workflow-templates":
                continue
            paths.append(path)
    return paths


def get_gitlink_sha(treeish: str, path: str) -> Optional[str]:
    """Return the gitlink SHA for a submodule path at the given treeish."""
    try:
        output = run_git(["ls-tree", treeish, "--", path])
    except subprocess.CalledProcessError:
        return None
    if not output:
        return None
    first_line = output.splitlines()[0]
    parts = first_line.split()
    if len(parts) < 3 or parts[1] != "commit":
        return None
    return parts[2]


def filter_tags(
    tags: List[str],
    prefix: Optional[str] = None,
    exclude_substring: Optional[str] = None,
) -> List[str]:
    """Filter tag names by prefix and/or substring exclusion."""
    filtered: List[str] = []
    for tag in tags:
        if prefix and not tag.startswith(prefix):
            continue
        if exclude_substring and exclude_substring in tag:
            continue
        filtered.append(tag)
    return filtered


def get_tags_for_commit(
    commit: str,
    prefix: Optional[str] = None,
    exclude_substring: Optional[str] = None,
) -> List[str]:
    """Return tags pointing at the given commit, with optional filtering."""
    try:
        tags_raw = run_git(["tag", "--points-at", commit])
    except subprocess.CalledProcessError:
        return []
    tags = [t for t in tags_raw.splitlines() if t]
    return filter_tags(tags, prefix=prefix, exclude_substring=exclude_substring)


def normalize_remote_url(url: str, token: Optional[str]) -> str:
    """Convert SSH URLs to HTTPS and inject token if provided."""
    if url.startswith("git@github.com:"):
        url = url.replace("git@github.com:", "https://github.com/")
    if token and url.startswith("https://"):
        url = url.replace("https://", f"https://x-access-token:{token}@")
    return url


def get_remote_tags(path: str, token: Optional[str]) -> Dict[str, List[str]]:
    """Return mapping of commit SHA -> tags from the remote without fetching."""
    remote_url = run_git(["-C", path, "remote", "get-url", "origin"], check=False).strip()
    if not remote_url:
        return {}

    url = normalize_remote_url(remote_url, token)
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"

    result = subprocess.run(
        ["git", "ls-remote", "--tags", url],
        text=True,
        capture_output=True,
        env=env,
    )
    if result.returncode != 0:
        msg = result.stderr.strip() or result.stdout.strip()
        print(f"Warning: could not list remote tags for {path}: {msg}", file=sys.stderr)
        return {}

    tags: Dict[str, List[str]] = {}
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) != 2:
            continue
        sha, ref = parts
        if not ref.startswith("refs/tags/"):
            continue
        if ref.endswith("^{}"):
            tag_name = ref[len("refs/tags/") : -3]
        else:
            tag_name = ref[len("refs/tags/") :]
        tags.setdefault(sha, []).append(tag_name)
    return tags


def describe_commit(
    commit: Optional[str],
    remote_tags: Dict[str, List[str]],
    prefix: Optional[str] = None,
    exclude_substring: Optional[str] = None,
) -> str:
    """Return a tag description for the commit or a fallback string."""
    if not commit:
        return "(missing)"

    tags = get_tags_for_commit(commit, prefix=prefix, exclude_substring=exclude_substring)
    if tags:
        return tags[0]

    remote = filter_tags(remote_tags.get(commit, []), prefix=prefix, exclude_substring=exclude_substring)
    if remote:
        return remote[0]

    try:
        describe_args = ["describe", "--tags", "--abbrev=8"]
        if prefix:
            describe_args.extend(["--match", f"{prefix}*"])
        elif exclude_substring:
            describe_args.extend(["--exclude", f"*{exclude_substring}*"])
        nearest = run_git(describe_args + [commit], check=False)
    except subprocess.CalledProcessError:
        nearest = ""
    nearest = nearest.strip()
    if nearest:
        return nearest

    try:
        short_sha = run_git(["rev-parse", "--short", commit])
    except subprocess.CalledProcessError:
        short_sha = commit[:7]
    return f"(no tag @ {short_sha})"


def main() -> int:
    base_sha = os.environ.get("BASE_COMMIT_SHA", "").strip()
    if not base_sha:
        print("BASE_COMMIT_SHA is not set; cannot generate release notes.", file=sys.stderr)
        return 1

    head_sha = run_git(["rev-parse", "HEAD"])

    print("::group::Submodule release notes")
    print(f"Comparing submodule tags between:")
    print(f"  Base: {base_sha}")
    print(f"  Head: {head_sha}")
    print()

    paths = get_submodule_paths()
    if not paths:
        print("No submodules found.")
        print("::endgroup::")
        return 0

    token = (
        os.environ.get("GIT_AUTH_TOKEN")
        or os.environ.get("ACTIONS_BOT_PAT")
        or os.environ.get("GITHUB_TOKEN")
    )

    for path in paths:
        remote_tags = get_remote_tags(path, token)

        old_sha = get_gitlink_sha(base_sha, path)
        new_sha = None
        try:
            new_sha = run_git(["-C", path, "rev-parse", "HEAD"])
        except subprocess.CalledProcessError:
            new_sha = None

        old_desc = describe_commit(old_sha, remote_tags, exclude_substring=BOOTLOADER_EXCLUDE_SUBSTRING)
        new_desc = describe_commit(new_sha, remote_tags, exclude_substring=BOOTLOADER_EXCLUDE_SUBSTRING)

        print(f"{path}:")
        print(f"  old: {old_desc}")
        print(f"  new: {new_desc}")

        bootloader_prefix = BOOTLOADER_TAG_PREFIXES.get(path)
        if bootloader_prefix:
            old_bl_desc = describe_commit(old_sha, remote_tags, prefix=bootloader_prefix)
            new_bl_desc = describe_commit(new_sha, remote_tags, prefix=bootloader_prefix)
            print(f"  bootloader old: {old_bl_desc}")
            print(f"  bootloader new: {new_bl_desc}")
        print()

    print("::endgroup::")
    return 0


if __name__ == "__main__":
    sys.exit(main())
