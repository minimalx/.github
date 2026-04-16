#!/usr/bin/env python3
import argparse
import json
import re
import sys
from pathlib import Path


MAX_IOT_DOCUMENT_BYTES = 32768
SEMVER_RE = re.compile(r"^v?\d+\.\d+\.\d+(?:-dev\d+)?$", re.IGNORECASE)
TEMPLATE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
DOCUMENT_SOURCE_STYLES = ("virtual-hosted", "path")


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
    render.add_argument(
        "--document-source-style",
        choices=DOCUMENT_SOURCE_STYLES,
        default="virtual-hosted",
    )
    render.add_argument("--inline-document-file")
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
    data = load_json_value(path)
    if not isinstance(data, dict):
        raise ValueError(f"'{path}' must contain a JSON object")
    return data


def load_json_value(path: Path):
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"Could not read '{path}': {exc}") from exc

    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in '{path}': {exc}") from exc


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


def normalize_s3_key(*, key_prefix: str, version: str) -> str:
    normalized_key_prefix = str(key_prefix).strip().strip("/")
    if not normalized_key_prefix:
        raise ValueError("S3 key prefix is required")
    return f"{normalized_key_prefix}/{version}.json"


def build_document_source(
    *,
    bucket: str,
    region: str,
    s3_key: str,
    style: str,
) -> str:
    normalized_bucket = str(bucket).strip()
    normalized_region = str(region).strip()
    if not normalized_bucket:
        raise ValueError("S3 bucket is required")
    if not normalized_region:
        raise ValueError("AWS region is required")
    if style == "path":
        return f"https://s3.{normalized_region}.amazonaws.com/{normalized_bucket}/{s3_key}"
    if style == "virtual-hosted":
        return f"https://{normalized_bucket}.s3.{normalized_region}.amazonaws.com/{s3_key}"
    raise ValueError(f"Unsupported document source style '{style}'")


def canonicalize_json_value(value) -> str:
    return json.dumps(value, separators=(",", ":"), sort_keys=True)


def canonicalize_document_string(value: str, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a JSON string")

    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{field_name} is not valid JSON: {exc}") from exc

    return canonicalize_json_value(parsed)


def load_inline_document(path: Path) -> str:
    parsed = load_json_value(path)
    canonical_document = canonicalize_json_value(parsed)
    document_size = len(canonical_document.encode("utf-8"))
    if document_size > MAX_IOT_DOCUMENT_BYTES:
        raise ValueError(
            "Inline document exceeds AWS IoT limit of "
            f"{MAX_IOT_DOCUMENT_BYTES} bytes: {document_size}"
        )
    return canonical_document


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
    document_source_style: str,
    inline_document_file: str | None,
    timeout_minutes: int,
) -> dict[str, object]:
    normalized_release_version = normalize_release_version(version)
    normalized_vehicle_type = normalize_vehicle_type(vehicle_type)
    normalized_role_arn = str(presigned_url_role_arn).strip()
    if not normalized_role_arn:
        raise ValueError("Presigned URL role ARN is required")
    if timeout_minutes < 1 or timeout_minutes > 10080:
        raise ValueError("timeout-minutes must be between 1 and 10080")

    s3_key = normalize_s3_key(
        key_prefix=key_prefix,
        version=normalized_release_version,
    )
    request: dict[str, object] = {
        "jobTemplateId": sanitize_template_id(
            template_id_prefix=template_id_prefix,
            release_version=normalized_release_version,
        ),
        "description": (
            f"{normalized_vehicle_type} firmware-upgrade manifest "
            f"v{normalized_release_version}"
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

    if inline_document_file:
        request["document"] = load_inline_document(Path(inline_document_file))
    else:
        request["documentSource"] = build_document_source(
            bucket=bucket,
            region=region,
            s3_key=s3_key,
            style=document_source_style,
        )

    return request


def compare_request_to_describe_output(expected: dict, actual: dict) -> list[str]:
    mismatches: list[str] = []

    checks = [
        ("jobTemplateId", expected.get("jobTemplateId"), actual.get("jobTemplateId")),
        ("description", expected.get("description"), actual.get("description")),
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

    expected_document = expected.get("document")
    actual_document = actual.get("document")
    if expected_document is not None:
        if actual_document is None:
            mismatches.append("document mismatch: expected inline document, got none")
        else:
            expected_canonical = canonicalize_document_string(
                expected_document,
                field_name="expected document",
            )
            actual_canonical = canonicalize_document_string(
                actual_document,
                field_name="actual document",
            )
            if expected_canonical != actual_canonical:
                mismatches.append("document mismatch: expected inline document content differs")
    elif actual_document is not None:
        mismatches.append("document mismatch: expected no inline document")

    expected_document_source = expected.get("documentSource")
    actual_document_source = actual.get("documentSource")
    if expected_document_source is not None:
        if expected_document_source != actual_document_source:
            mismatches.append(
                "documentSource mismatch: "
                f"expected {expected_document_source!r}, got {actual_document_source!r}"
            )
    elif actual_document_source is not None:
        mismatches.append("documentSource mismatch: expected no documentSource")

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
        document_source_style=args.document_source_style,
        inline_document_file=args.inline_document_file,
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
