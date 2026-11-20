#!/usr/bin/env python3
"""Write submodule_versions.txt: "<path> <app version> [<bootloader version>]".

A board's version comes from the git tags on the submodule commit the manifest
pins. The channel says which tags count:

  release      (default) only release tags, <prefix>X.Y.Z. dev/ tags are ignored
               and a suffixed version is refused, never cut down to X.Y.Z, so a
               release manifest can't pin a development build. A board pinned at
               an untagged commit gets an empty version and the manifest
               generator fails.
  development  a release tag when the commit has one, otherwise its development
               tag dev/<prefix>X.Y.Z-devN (board CI, workflow-templates
               stm32-release dev-tag), keeping the -devN.

The bootloader may be released less often than the app: when the commit has no
bootloader tag, the nearest one reachable from it is used (release tags only on
the release channel, release or dev/ tags on the development channel).
"""
import argparse
import subprocess
import re
from pathlib import Path

BOOTLOADER_TAG_PREFIXES = {
    "body-control-unit": "BCU_BL_v",
    "avas": "AVAS_BL_v",
    "security-module": "SM_BL_v",
    "pmu": "PMU_BL_v",
}
BOOTLOADER_TAG_SUBSTRING = "_BL_"
DEV_TAG_NAMESPACE = "dev/"
CHANNELS = ("release", "development")
# The version must end the tag: "BCU_APP_v4.4.9-rc1" is not read as 4.4.9.
_END = r"(?![0-9A-Za-z.+-])"
SEMVER_PATTERN = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+" + _END)
DEV_SEMVER_PATTERN = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+-dev[0-9]+" + _END)

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

def extract_semver(tag):
    """X.Y.Z from a release tag, X.Y.Z-devN from a dev/ tag; "" otherwise."""
    if tag.startswith(DEV_TAG_NAMESPACE):
        match = DEV_SEMVER_PATTERN.search(tag)
    else:
        match = SEMVER_PATTERN.search(tag)
    return match.group(0) if match else ""


def usable_tags(tags, channel):
    """Release tags first; dev/ tags after them, and only on the development channel."""
    release = [t for t in tags if not t.startswith(DEV_TAG_NAMESPACE)]
    if channel != "development":
        return release
    return release + [t for t in tags if t.startswith(DEV_TAG_NAMESPACE)]


def without_namespace(tag):
    return tag[len(DEV_TAG_NAMESPACE):] if tag.startswith(DEV_TAG_NAMESPACE) else tag


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--channel", choices=CHANNELS, default="release")
    return parser.parse_args(argv)


def main(argv=None):
    channel = parse_args(argv).channel
    root = Path.cwd()
    output_file = root / "submodule_versions.txt"
    print(f"Channel: {channel}")

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
                tags_all = [t for t in tags_raw.splitlines() if t]
            except subprocess.CalledProcessError:
                tags_all = []

            tags_all = usable_tags(tags_all, channel)
            tags_list = [t for t in tags_all if BOOTLOADER_TAG_SUBSTRING not in t]
            bootloader_prefix = BOOTLOADER_TAG_PREFIXES.get(path)
            bootloader_tags = (
                [t for t in tags_all if without_namespace(t).startswith(bootloader_prefix)]
                if bootloader_prefix
                else []
            )

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
                version = extract_semver(first_tag)
                if not version:
                    print(f"Warning: could not parse version from tag '{first_tag}'")

            bootloader_version = ""
            if bootloader_prefix:
                if not bootloader_tags:
                    print("Bootloader tags:   (none pointing at commit)")
                    # Bootloaders change rarely, so a release may not re-tag the
                    # bootloader at the app commit. Fall back to the most recent
                    # bootloader tag reachable from HEAD (the last valid one).
                    match = ["--match", f"{bootloader_prefix}*"]
                    if channel == "development":
                        match += ["--match", f"{DEV_TAG_NAMESPACE}{bootloader_prefix}*"]
                    nearest_boot_tag = run_git(
                        ["-C", path, "describe", "--tags", "--abbrev=0", *match, "HEAD"],
                        check=False,
                    )
                    if nearest_boot_tag:
                        print(f"Nearest bootloader tag: {nearest_boot_tag}")
                        bootloader_version = extract_semver(nearest_boot_tag)
                        if not bootloader_version:
                            print(
                                f"Warning: could not parse bootloader version from tag '{nearest_boot_tag}'"
                            )
                else:
                    print("Bootloader tags:")
                    for t in bootloader_tags:
                        print(f"  - {t}")

                    first_boot_tag = bootloader_tags[0]
                    bootloader_version = extract_semver(first_boot_tag)
                    if not bootloader_version:
                        print(
                            f"Warning: could not parse bootloader version from tag '{first_boot_tag}'"
                        )

            print(f"Commit: {short_sha} ({commit_sha})")

            # Write "<path> <version>" to submodule_versions.txt
            if bootloader_version:
                f.write(f"{path} {version} {bootloader_version}\n")
            else:
                f.write(f"{path} {version}\n")

    print("::endgroup::")

if __name__ == "__main__":
    main()
