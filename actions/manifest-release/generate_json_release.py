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
    return parser.parse_args()

def main():
    args = parse_args()
    submodules_path = Path(args.submodules_file)

    if not submodules_path.is_file():
        print(f"{submodules_path} not found", file=sys.stderr)
        sys.exit(1)

    # ISO 8601 UTC timestamp
    date_str = datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ")
    creator = os.environ.get("GITHUB_ACTOR", "")

    submodules = []
    with submodules_path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue

            parts = line.split(maxsplit=1)
            name = parts[0]
            version = parts[1] if len(parts) == 2 else ""
            submodules.append({"name": name, "version": version})

    data = {
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
