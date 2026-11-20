import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "generate_json_release.py"


class GenerateJsonReleaseTest(unittest.TestCase):
    def generate(self, submodule_versions: str) -> list[dict]:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            (tmp_path / "submodule_versions.txt").write_text(submodule_versions)
            result = subprocess.run(
                [sys.executable, str(SCRIPT), "-o", "release.json"],
                cwd=tmp_path, capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            return json.loads((tmp_path / "release.json").read_text())["submodules"]

    def test_missing_app_version_keeps_the_bootloader_in_its_field(self):
        # collect_submodules.py writes "-" for a board with no app version.
        self.assertEqual(
            self.generate("body-control-unit - 2.2.11\nhmi 0.3.11\n"),
            [
                {"name": "body-control-unit", "version": "", "bootloader_version": "2.2.11"},
                {"name": "hmi", "version": "0.3.11"},
            ],
        )

    def test_versions_are_unchanged(self):
        self.assertEqual(
            self.generate("body-control-unit 4.4.9-dev98 2.2.12-dev98\n"),
            [{"name": "body-control-unit", "version": "4.4.9-dev98", "bootloader_version": "2.2.12-dev98"}],
        )


if __name__ == "__main__":
    unittest.main()
