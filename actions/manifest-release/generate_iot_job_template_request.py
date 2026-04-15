#!/usr/bin/env python3
import argparse
import json
import re
import sys
from pathlib import Path


SEMVER_RE = re.compile(r"^v?\d+\.\d+\.\d+(?:-dev\d+)?$", re.IGNORECASE)
TEMPLATE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def parse_args():
    parser = argparse.ArgumentParser(
        description="Render and compare AWS IoT Core job template requests"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    render = subparsers.add_parser(
        "render",
        help="Generate an AWS IoT CreateJobTemplate request JSON file",
    )
    render.add_argument("--vehicle-type", required=True)
    render.add_argument("--version", required=True)
    render.add_argument("--bucket", required=True)
    render.add_argument("--region", required=True)
    render.add_argument("--key-prefix", required=True)
    render.add_argument("--template-id-prefix", required=True)
    render.add_argument("--source-branch", required=True)
    render.add_argument("--presigned-url-role-arn", required=True)
    render.add_argument("--timeout-minutes", required=True, type=int)
    render.add_argument("-o", "--output", required=True)

    compare = subparsers.add_parser(
        "compare",
        help="Compare a rendered request against describe-job-template output",
    )
    compare.add_argument("--expected-file", required=True)
    compare.add_argument("--actual-file", required=True)

    return parser.parse_args()


def load_json_object(path: Path) -> dict:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"Could not read '{path}': {exc}") from exc

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in '{path}': {exc}") from exc

    if not isinstance(data, dict):
        raise ValueError(f"'{path}' must contain a JSON object")
    return data


def normalize_release_version(raw_version: str) -> str:
    version = str(raw_version).strip()
    if not version:
        raise ValueError("Release version is required")
    if not SEMVER_RE.fullmatch(version):
        raise ValueError(f"Invalid release version '{raw_version}'")
    return version[1:] if version.lower().startswith("v") else version


def normalize_vehicle_type(raw_vehicle_type: str) -> str:
    vehicle_type = str(raw_vehicle_type).strip()
    if not vehicle_type:
        raise ValueError("Vehicle type is required")
    return vehicle_type.replace("_", "-")


def sanitize_template_id(
    *, template_id_prefix: str, release_version: str
) -> str:
    prefix = str(template_id_prefix).strip()
    if not prefix:
        raise ValueError("Template ID prefix is required")

    suffix = re.sub(r"[^A-Za-z0-9_]", "_", release_version)
    template_id = f"{prefix}{suffix}"
    if not TEMPLATE_ID_RE.fullmatch(template_id):
        raise ValueError(f"Invalid job template id '{template_id}'")
    return template_id


def build_document_source(*, bucket: str, region: str, key_prefix: str, version: str) -> str:
    normalized_bucket = str(bucket).strip()
    normalized_region = str(region).strip()
    normalized_key_prefix = str(key_prefix).strip().strip("/")
    if not normalized_bucket:
        raise ValueError("S3 bucket is required")
    if not normalized_region:
        raise ValueError("AWS region is required")
    if not normalized_key_prefix:
        raise ValueError("S3 key prefix is required")
    return (
        f"https://{normalized_bucket}.s3.{normalized_region}.amazonaws.com/"
        f"{normalized_key_prefix}/{version}.json"
    )


def build_tags(
    *,
    vehicle_type: str,
    release_version: str,
    source_branch: str,
    s3_key: str,
) -> list[dict[str, str]]:
    branch = str(source_branch).strip()
    if not branch:
        raise ValueError("Source branch is required")

    return [
        {"Key": "operation", "Value": "firmware-upgrade"},
        {"Key": "vehicleType", "Value": vehicle_type},
        {"Key": "manifestVersion", "Value": f"v{release_version}"},
        {"Key": "sourceBranch", "Value": branch},
        {"Key": "s3Key", "Value": s3_key},
    ]


def render_request(
    *,
    vehicle_type: str,
    version: str,
    bucket: str,
    region: str,
    key_prefix: str,
    template_id_prefix: str,
    source_branch: str,
    presigned_url_role_arn: str,
    timeout_minutes: int,
) -> dict[str, object]:
    normalized_release_version = normalize_release_version(version)
    normalized_vehicle_type = normalize_vehicle_type(vehicle_type)
    normalized_role_arn = str(presigned_url_role_arn).strip()
    if not normalized_role_arn:
        raise ValueError("Presigned URL role ARN is required")
    if timeout_minutes < 1 or timeout_minutes > 10080:
        raise ValueError("timeout-minutes must be between 1 and 10080")

    s3_key = f"{str(key_prefix).strip().strip('/')}/{normalized_release_version}.json"
    request = {
        "jobTemplateId": sanitize_template_id(
            template_id_prefix=template_id_prefix,
            release_version=normalized_release_version,
        ),
        "description": (
            f"{normalized_vehicle_type} firmware-upgrade manifest "
            f"v{normalized_release_version}"
        ),
        "documentSource": build_document_source(
            bucket=bucket,
            region=region,
            key_prefix=key_prefix,
            version=normalized_release_version,
        ),
        "presignedUrlConfig": {"roleArn": normalized_role_arn},
        "timeoutConfig": {"inProgressTimeoutInMinutes": timeout_minutes},
        "tags": build_tags(
            vehicle_type=normalized_vehicle_type,
            release_version=normalized_release_version,
            source_branch=source_branch,
            s3_key=s3_key,
        ),
    }
    return request


def compare_request_to_describe_output(expected: dict, actual: dict) -> list[str]:
    mismatches: list[str] = []

    checks = [
        ("jobTemplateId", expected.get("jobTemplateId"), actual.get("jobTemplateId")),
        ("description", expected.get("description"), actual.get("description")),
        ("documentSource", expected.get("documentSource"), actual.get("documentSource")),
        (
            "presignedUrlConfig.roleArn",
            ((expected.get("presignedUrlConfig") or {}).get("roleArn")),
            ((actual.get("presignedUrlConfig") or {}).get("roleArn")),
        ),
        (
            "timeoutConfig.inProgressTimeoutInMinutes",
            ((expected.get("timeoutConfig") or {}).get("inProgressTimeoutInMinutes")),
            ((actual.get("timeoutConfig") or {}).get("inProgressTimeoutInMinutes")),
        ),
    ]

    for name, expected_value, actual_value in checks:
        if expected_value != actual_value:
            mismatches.append(
                f"{name} mismatch: expected {expected_value!r}, got {actual_value!r}"
            )

    return mismatches


def command_render(args) -> int:
    request = render_request(
        vehicle_type=args.vehicle_type,
        version=args.version,
        bucket=args.bucket,
        region=args.region,
        key_prefix=args.key_prefix,
        template_id_prefix=args.template_id_prefix,
        source_branch=args.source_branch,
        presigned_url_role_arn=args.presigned_url_role_arn,
        timeout_minutes=args.timeout_minutes,
    )

    output_path = Path(args.output)
    output_path.write_text(json.dumps(request, indent=2) + "\n", encoding="utf-8")

    print(f"Generated {output_path}:")
    print(output_path.read_text(encoding="utf-8"))
    return 0


def command_compare(args) -> int:
    expected = load_json_object(Path(args.expected_file))
    actual = load_json_object(Path(args.actual_file))
    mismatches = compare_request_to_describe_output(expected, actual)

    if mismatches:
        for mismatch in mismatches:
            print(mismatch, file=sys.stderr)
        return 1

    print("AWS IoT job template matches expected request.")
    return 0


def main() -> int:
    args = parse_args()

    try:
        if args.command == "render":
            return command_render(args)
        return command_compare(args)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
