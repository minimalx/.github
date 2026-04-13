#!/usr/bin/env python3
import argparse
import json
import re
import sys
from pathlib import Path


SEMVER_RE = re.compile(r"^v?\d+\.\d+\.\d+(?:-dev\d+)?$", re.IGNORECASE)
VALID_FIELDS = {"app", "boot"}


def parse_args():
    parser = argparse.ArgumentParser(
        description="Generate an ordered firmware-upgrade manifest from submodule_versions.txt"
    )
    parser.add_argument(
        "--layout-file",
        required=True,
        help="Path to the checked-in manifest layout specification",
    )
    parser.add_argument(
        "--version",
        required=True,
        help="Release version used in manifestVersion and output naming",
    )
    parser.add_argument(
        "-o",
        "--output",
        required=True,
        help="Output JSON file name",
    )
    parser.add_argument(
        "-s",
        "--submodules-file",
        default="submodule_versions.txt",
        help="Input submodule versions file (default: submodule_versions.txt)",
    )
    parser.add_argument(
        "-e",
        "--ext-versions",
        default=None,
        help="Optional external JSON file with additional version sources",
    )
    return parser.parse_args()


def normalize_release_version(raw_version: str) -> str:
    version = str(raw_version).strip()
    if not version:
        raise ValueError("Release version is required")
    if not SEMVER_RE.fullmatch(version):
        raise ValueError(f"Invalid release version '{raw_version}'")
    return version[1:] if version.lower().startswith("v") else version


def normalize_component_version(raw_version: str | None, *, context: str) -> str:
    version = "" if raw_version is None else str(raw_version).strip()
    if not version:
        raise ValueError(f"Missing {context}")
    if not SEMVER_RE.fullmatch(version):
        raise ValueError(f"Invalid {context}: '{raw_version}'")
    return version[1:] if version.lower().startswith("v") else version


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


def load_submodule_versions(path: Path) -> dict[str, dict[str, str]]:
    if not path.is_file():
        raise ValueError(f"{path} not found")

    versions: dict[str, dict[str, str]] = {}
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue

            parts = stripped.split(maxsplit=2)
            if not parts:
                continue

            source = parts[0]
            entry: dict[str, str] = {}
            if len(parts) >= 2:
                entry["app"] = parts[1]
            if len(parts) >= 3:
                entry["boot"] = parts[2]

            if source in versions:
                raise ValueError(
                    f"Duplicate source '{source}' in {path} at line {line_number}"
                )
            versions[source] = entry

    return versions


def load_external_versions(path: Path | None) -> dict[str, dict[str, str]]:
    if path is None or not str(path).strip():
        return {}

    data = load_json_object(path)
    submodules = data.get("submodules", [])
    if not isinstance(submodules, list):
        raise ValueError(f"'submodules' in '{path}' must be a list")

    versions: dict[str, dict[str, str]] = {}
    for index, item in enumerate(submodules):
        if not isinstance(item, dict):
            raise ValueError(
                f"External source entry #{index} in '{path}' must be an object"
            )

        source = item.get("name")
        if not isinstance(source, str) or not source.strip():
            raise ValueError(
                f"External source entry #{index} in '{path}' needs a non-empty name"
            )

        entry: dict[str, str] = {}
        version = item.get("version")
        boot_version = item.get("bootloader_version")
        if version is not None:
            entry["app"] = str(version)
        if boot_version is not None:
            entry["boot"] = str(boot_version)

        if source in versions:
            raise ValueError(f"Duplicate external source '{source}' in '{path}'")
        versions[source] = entry

    return versions


def merge_versions(
    primary: dict[str, dict[str, str]],
    extra: dict[str, dict[str, str]],
) -> dict[str, dict[str, str]]:
    merged = dict(primary)
    for source, entry in extra.items():
        if source in merged:
            raise ValueError(f"Duplicate source '{source}' across version inputs")
        merged[source] = entry
    return merged


def validate_field_order(field_order: object, *, board: str) -> list[str]:
    if not isinstance(field_order, list) or not field_order:
        raise ValueError(f"Board '{board}' must define a non-empty fieldOrder list")

    normalized: list[str] = []
    for raw_field in field_order:
        field = str(raw_field).strip().lower()
        if field not in VALID_FIELDS:
            raise ValueError(f"Board '{board}' has unsupported field '{raw_field}'")
        if field in normalized:
            raise ValueError(f"Board '{board}' repeats field '{field}' in fieldOrder")
        normalized.append(field)

    if "app" not in normalized:
        raise ValueError(f"Board '{board}' fieldOrder must include 'app'")
    return normalized


def load_layout(path: Path) -> tuple[str, str, list[dict[str, object]]]:
    data = load_json_object(path)

    operation = data.get("operation")
    vehicle_type = data.get("vehicleType")
    board_sequence = data.get("boardSequence")

    if not isinstance(operation, str) or not operation.strip():
        raise ValueError(f"'{path}' must define a non-empty 'operation'")
    if not isinstance(vehicle_type, str) or not vehicle_type.strip():
        raise ValueError(f"'{path}' must define a non-empty 'vehicleType'")
    if not isinstance(board_sequence, list) or not board_sequence:
        raise ValueError(f"'{path}' must define a non-empty 'boardSequence'")

    seen_boards: set[str] = set()
    normalized_sequence: list[dict[str, object]] = []
    for entry in board_sequence:
        if not isinstance(entry, dict):
            raise ValueError(f"Each boardSequence entry in '{path}' must be an object")

        board = entry.get("board")
        app_source = entry.get("appSource")
        boot_source = entry.get("bootSource")

        if not isinstance(board, str) or not board.strip():
            raise ValueError(f"Each boardSequence entry in '{path}' needs a board name")
        if board in seen_boards:
            raise ValueError(f"Board '{board}' is duplicated in '{path}'")
        if not isinstance(app_source, str) or not app_source.strip():
            raise ValueError(f"Board '{board}' must define a non-empty appSource")
        if boot_source is not None and not isinstance(boot_source, str):
            raise ValueError(f"Board '{board}' bootSource must be a string or null")

        field_order = validate_field_order(entry.get("fieldOrder"), board=board)
        if boot_source is not None and "boot" not in field_order:
            raise ValueError(
                f"Board '{board}' defines bootSource but fieldOrder does not include 'boot'"
            )

        seen_boards.add(board)
        normalized_sequence.append(
            {
                "board": board,
                "fieldOrder": field_order,
                "appSource": app_source.strip(),
                "bootSource": None if boot_source is None else boot_source.strip(),
            }
        )

    return operation.strip(), vehicle_type.strip(), normalized_sequence


def resolve_version(
    versions: dict[str, dict[str, str]],
    *,
    source: str | None,
    field: str,
    board: str,
) -> str | None:
    if source is None:
        return None
    if source not in versions:
        raise ValueError(f"Unknown {field} source '{source}' for board '{board}'")

    return normalize_component_version(
        versions[source].get(field),
        context=f"{field} version for board '{board}' from source '{source}'",
    )


def build_manifest(
    *,
    operation: str,
    vehicle_type: str,
    release_version: str,
    board_sequence: list[dict[str, object]],
    versions: dict[str, dict[str, str]],
) -> dict[str, object]:
    boards: dict[str, dict[str, object]] = {}

    for board_spec in board_sequence:
        board = str(board_spec["board"])
        board_payload: dict[str, object] = {}
        for field in board_spec["fieldOrder"]:
            if field == "app":
                board_payload["app"] = resolve_version(
                    versions,
                    source=str(board_spec["appSource"]),
                    field="app",
                    board=board,
                )
            elif field == "boot":
                boot_source = board_spec["bootSource"]
                if boot_source is None:
                    board_payload["boot"] = None
                else:
                    board_payload["boot"] = resolve_version(
                        versions,
                        source=str(boot_source),
                        field="boot",
                        board=board,
                    )
        boards[board] = board_payload

    return {
        "operation": operation,
        "manifestVersion": f"v{release_version}",
        "vehicleType": vehicle_type,
        "boards": boards,
    }


def main() -> int:
    args = parse_args()

    try:
        release_version = normalize_release_version(args.version)
        versions = load_submodule_versions(Path(args.submodules_file))
        versions = merge_versions(
            versions,
            load_external_versions(
                Path(args.ext_versions) if args.ext_versions else None
            ),
        )
        operation, vehicle_type, board_sequence = load_layout(Path(args.layout_file))
        manifest = build_manifest(
            operation=operation,
            vehicle_type=vehicle_type,
            release_version=release_version,
            board_sequence=board_sequence,
            versions=versions,
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    output_path = Path(args.output)
    output_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    print(f"Generated {output_path}:")
    print(output_path.read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
