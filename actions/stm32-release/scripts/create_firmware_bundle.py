#!/usr/bin/env python3
import os
import shutil
import sys
from pathlib import Path


def main() -> int:
    filename = os.environ.get("FILENAME")
    if not filename:
        print("FILENAME environment variable is not set.", file=sys.stderr)
        return 1

    release_dir = Path("release")
    artifacts_dir = release_dir / "artifacts"
    if not artifacts_dir.is_dir():
        print(
            f"Expected directory '{artifacts_dir}' to exist with firmware artifacts.",
            file=sys.stderr,
        )
        return 1

    folder_name = Path(filename).stem
    temp_dir = release_dir / folder_name

    # Move artifacts -> renamed folder temporarily
    if temp_dir.exists():
        print(
            f"Temporary directory '{temp_dir}' already exists. "
            "Refusing to overwrite.",
            file=sys.stderr,
        )
        return 1

    artifacts_dir.rename(temp_dir)

    try:
        # Create zip in the parent of 'release' (i.e., repo root / cwd),
        # matching: (cd release && zip -r "../$FILENAME" "$folder_name")
        base_name = Path(filename).with_suffix("")  # strip .zip
        shutil.make_archive(
            base_name=str(base_name),
            format="zip",
            root_dir=str(release_dir),
            base_dir=folder_name,
        )
    finally:
        # Restore original directory layout
        temp_dir.rename(artifacts_dir)

    zip_path = Path(filename)
    if not zip_path.is_file():
        print(f"Expected zip file '{zip_path}' to be created.", file=sys.stderr)
        return 1

    # Approximate `ls -l "$FILENAME"` with a simple size log
    size = zip_path.stat().st_size
    print(f"{zip_path} created ({size} bytes)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
