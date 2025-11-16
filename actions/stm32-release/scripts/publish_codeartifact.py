#!/usr/bin/env python3
import argparse
import hashlib
import os
import subprocess
import sys
from pathlib import Path


def compute_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description="Publish generic package to AWS CodeArtifact."
    )
    parser.add_argument(
        "--repository",
        required=True,
        help="CodeArtifact repository name (e.g., DEV or PROD repo).",
    )

    args = parser.parse_args(argv[1:])

    version = os.environ.get("VERSION")
    package = os.environ.get("PACKAGE")
    filename = os.environ.get("FILENAME")
    namespace = os.environ.get("NAMESPACE")

    if not version or not package or not filename:
        print(
            "VERSION, PACKAGE and FILENAME environment variables must be set.",
            file=sys.stderr,
        )
        return 1

    if not namespace:
        print("NAMESPACE environment variable must be set.", file=sys.stderr)
        return 1

    domain = os.environ.get("AWS_DOMAIN")
    domain_owner = os.environ.get("AWS_DOMAIN_OWNER")

    if not domain or not domain_owner:
        print(
            "AWS_DOMAIN and AWS_DOMAIN_OWNER environment variables must be set.",
            file=sys.stderr,
        )
        return 1

    asset_path = Path(filename)
    if not asset_path.is_file():
        print(
            f"Asset file '{asset_path}' does not exist; cannot publish.",
            file=sys.stderr,
        )
        return 1

    asset_sha256 = compute_sha256(asset_path)

    cmd = [
        "aws",
        "codeartifact",
        "publish-package-version",
        "--domain",
        domain,
        "--domain-owner",
        domain_owner,
        "--repository",
        args.repository,
        "--format",
        "generic",
        "--namespace",
        namespace,
        "--package",
        package,
        "--package-version",
        version,
        "--asset-content",
        str(asset_path),
        "--asset-name",
        asset_path.name,
        "--asset-sha256",
        asset_sha256,
    ]

    print("Running:", " ".join(cmd))
    result = subprocess.run(cmd, check=False)
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
