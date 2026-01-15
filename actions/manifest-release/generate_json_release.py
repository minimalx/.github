#!/usr/bin/env python3
import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

def parse_args():
    parser = argparse.ArgumentParser(
        description="Generate release metadata JSON from submodule_versions.txt"
    )
    parser.add_argument(
        "-o", "--output",
        dest="output",
        default="release.json",
        help="Output JSON file name (default: release.json)",
    )
    parser.add_argument(
        "-s", "--submodules-file",
        dest="submodules_file",
        default="submodule_versions.txt",
        help="Input submodule versions file (default: submodule_versions.txt)",
    )
    parser.add_argument(
        "-e", "--ext-versions",
        dest="ext_versions",
        default=None,
        help="Optional external JSON file with additional submodules",
    )
    return parser.parse_args()

def load_ext_submodules(path: Path):
    """Load additional submodules from a JSON file.

    Expected format:
    {
      "submodules": [
        {"name": "...", "version": "..."},
        ...
      ]
    }
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        print(f"Warning: could not read external versions file '{path}': {e}", file=sys.stderr)
        return []

    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        print(f"Warning: invalid JSON in external versions file '{path}': {e}", file=sys.stderr)
        return []

    if not isinstance(data, dict):
        print(f"Warning: external versions file '{path}' must contain a JSON object", file=sys.stderr)
        return []

    submodules = data.get("submodules", [])
    if not isinstance(submodules, list):
        print(f"Warning: 'submodules' in '{path}' must be a list", file=sys.stderr)
        return []

    normalized = []
    for idx, item in enumerate(submodules):
        if not isinstance(item, dict):
            print(f"Warning: submodule #{idx} in '{path}' is not an object, skipping", file=sys.stderr)
            continue
        name = item.get("name")
        version = item.get("version", "")
        bootloader_version = item.get("bootloader_version")
        if not isinstance(name, str):
            print(f"Warning: submodule #{idx} in '{path}' has no valid 'name', skipping", file=sys.stderr)
            continue
        if not isinstance(version, str):
            version = str(version)
        entry = {"name": name, "version": version}
        if bootloader_version is not None and not isinstance(bootloader_version, str):
            bootloader_version = str(bootloader_version)
        if bootloader_version:
            entry["bootloader_version"] = bootloader_version
        normalized.append(entry)

    return normalized

def main():
    args = parse_args()
    submodules_path = Path(args.submodules_file)

    if not submodules_path.is_file():
        print(f"{submodules_path} not found", file=sys.stderr)
        sys.exit(1)

    # ISO 8601 UTC timestamp
    date_str = datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ")
    creator = os.environ.get("GITHUB_ACTOR", "")

    # Parse main submodule file (plain text)
    submodules = []
    with submodules_path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue

            parts = line.split(maxsplit=2)
            name = parts[0]
            version = parts[1] if len(parts) >= 2 else ""
            bootloader_version = parts[2] if len(parts) >= 3 else ""
            entry = {"name": name, "version": version}
            if bootloader_version:
                entry["bootloader_version"] = bootloader_version
            submodules.append(entry)

    # Append external JSON submodules if provided
    if args.ext_versions:
        ext_path = Path(args.ext_versions)
        if ext_path.is_file():
            extra_submodules = load_ext_submodules(ext_path)
            submodules.extend(extra_submodules)
        else:
            print(f"Warning: external versions file '{ext_path}' not found. Skipping.", file=sys.stderr)

    data = {
        "format_version": "0.1",
        "date": date_str,
        "creator": creator,
        "submodules": submodules,
    }

    output_path = Path(args.output)
    output_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    print(f"Generated {output_path}:")
    print(output_path.read_text(encoding="utf-8"))

if __name__ == "__main__":
    main()
