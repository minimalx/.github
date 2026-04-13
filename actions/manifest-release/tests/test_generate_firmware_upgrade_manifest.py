import json
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]
SCRIPT = (
    ROOT
    / "workflow-templates/actions/manifest-release/generate_firmware_upgrade_manifest.py"
)
LAYOUT = ROOT / "manifest-layouts/p4-1.x-firmware-upgrade.json"

SUBMODULE_VERSIONS = """\
body-control-unit 4.0.0 2.1.1
security-module 3.2.1 3.1.4
tcu-stack 1.5.2
avas 2.4.1 2.0.3
"""


class GenerateFirmwareUpgradeManifestTests(unittest.TestCase):
    def run_script(
        self,
        *,
        submodule_versions: str,
        version: str = "1.3.1",
        output_name: str = "1.3.1.json",
        layout_text: str | None = None,
        ext_versions_text: str | None = None,
    ) -> tuple[subprocess.CompletedProcess[str], str | None, str]:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            submodules_path = temp_path / "submodule_versions.txt"
            submodules_path.write_text(submodule_versions, encoding="utf-8")

            layout_path = LAYOUT
            if layout_text is not None:
                layout_path = temp_path / "layout.json"
                layout_path.write_text(layout_text, encoding="utf-8")

            ext_versions_path = temp_path / "ext_versions.json"
            if ext_versions_text is not None:
                ext_versions_path.write_text(ext_versions_text, encoding="utf-8")

            output_path = temp_path / output_name
            command = [
                "python3",
                str(SCRIPT),
                "--layout-file",
                str(layout_path),
                "--version",
                version,
                "--output",
                str(output_path),
                "--submodules-file",
                str(submodules_path),
            ]
            if ext_versions_text is not None:
                command.extend(["--ext-versions", str(ext_versions_path)])

            result = subprocess.run(
                command,
                cwd=ROOT,
                text=True,
                capture_output=True,
            )

            if result.returncode == 0:
                return result, output_path.read_text(encoding="utf-8"), output_name

            return result, None, output_name

    def test_cli_generates_manifest_with_explicit_board_and_field_order(self):
        result, output_text, _ = self.run_script(submodule_versions=SUBMODULE_VERSIONS)

        self.assertEqual(result.returncode, 0, msg=result.stderr)

        self.assertIsNotNone(output_text)
        data = json.loads(output_text)
        self.assertEqual(
            list(data["boards"].keys()),
            ["AVA", "SMM", "SML", "SMB", "BCU", "TCU"],
        )
        self.assertEqual(list(data["boards"]["AVA"].keys()), ["app", "boot"])
        self.assertEqual(list(data["boards"]["TCU"].keys()), ["app", "boot"])
        self.assertEqual(data["boards"]["AVA"]["app"], "2.4.1")
        self.assertEqual(data["boards"]["AVA"]["boot"], "2.0.3")
        self.assertEqual(data["boards"]["SMM"]["app"], "3.2.1")
        self.assertEqual(data["boards"]["SMM"]["boot"], "3.1.4")
        self.assertEqual(data["boards"]["BCU"]["app"], "4.0.0")
        self.assertEqual(data["boards"]["BCU"]["boot"], "2.1.1")
        self.assertEqual(data["boards"]["TCU"]["app"], "1.5.2")
        self.assertIsNone(data["boards"]["TCU"]["boot"])

    def test_cli_uses_version_in_filename_and_manifest_version(self):
        result, output_text, output_name = self.run_script(
            submodule_versions=SUBMODULE_VERSIONS,
            version="1.3.7",
            output_name="1.3.7.json",
        )

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn(output_name, result.stdout)

        self.assertIsNotNone(output_text)
        data = json.loads(output_text)
        self.assertEqual(data["manifestVersion"], "v1.3.7")
        self.assertEqual(data["vehicleType"], "P4-1.X")
        self.assertEqual(data["operation"], "firmware-upgrade")

    def test_cli_fails_when_required_boot_version_is_missing(self):
        result, _, _ = self.run_script(
            submodule_versions="""\
body-control-unit 4.0.0 2.1.1
security-module 3.2.1
tcu-stack 1.5.2
avas 2.4.1 2.0.3
"""
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Missing boot version for board 'SMM'", result.stderr)

    def test_cli_fails_when_layout_uses_unknown_source(self):
        result, _, _ = self.run_script(
            submodule_versions=SUBMODULE_VERSIONS,
            layout_text="""\
{
  "operation": "firmware-upgrade",
  "vehicleType": "P4-1.X",
  "boardSequence": [
    {
      "board": "AVA",
      "fieldOrder": ["app", "boot"],
      "appSource": "does-not-exist",
      "bootSource": "avas"
    }
  ]
}
""",
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Unknown app source 'does-not-exist' for board 'AVA'", result.stderr)

    def test_cli_resolves_external_version_sources(self):
        result, output_text, _ = self.run_script(
            submodule_versions="tcu-stack 1.5.2\n",
            ext_versions_text="""\
{
  "submodules": [
    {"name": "PERS Firmware", "version": "v2.7.3"},
    {"name": "HMI Firmware", "version": "v0.2.0"},
    {"name": "Battery Firmware", "version": "v38.9.23"}
  ]
}
""",
            layout_text="""\
{
  "operation": "firmware-upgrade",
  "vehicleType": "P4-2.X",
  "boardSequence": [
    {
      "board": "PERS",
      "fieldOrder": ["app", "boot"],
      "appSource": "PERS Firmware",
      "bootSource": null
    },
    {
      "board": "HMI",
      "fieldOrder": ["app", "boot"],
      "appSource": "HMI Firmware",
      "bootSource": null
    },
    {
      "board": "BATTERY",
      "fieldOrder": ["app", "boot"],
      "appSource": "Battery Firmware",
      "bootSource": null
    },
    {
      "board": "TCU",
      "fieldOrder": ["app", "boot"],
      "appSource": "tcu-stack",
      "bootSource": null
    }
  ]
}
""",
        )

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIsNotNone(output_text)
        data = json.loads(output_text)
        self.assertEqual(list(data["boards"].keys()), ["PERS", "HMI", "BATTERY", "TCU"])
        self.assertEqual(data["boards"]["PERS"]["app"], "2.7.3")
        self.assertIsNone(data["boards"]["PERS"]["boot"])
        self.assertEqual(data["boards"]["HMI"]["app"], "0.2.0")
        self.assertEqual(data["boards"]["BATTERY"]["app"], "38.9.23")
        self.assertEqual(data["boards"]["TCU"]["app"], "1.5.2")


if __name__ == "__main__":
    unittest.main()
