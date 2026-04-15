import json
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]
SCRIPT = (
    ROOT
    / "workflow-templates/actions/manifest-release/generate_iot_job_template_request.py"
)


class GenerateIotJobTemplateRequestTests(unittest.TestCase):
    def run_render(
        self,
        *,
        vehicle_type: str = "P4_1.X",
        version: str = "1.3.1",
        bucket: str = "vehicle-iot-manifest-update-dev-303188940251",
        region: str = "eu-central-1",
        key_prefix: str = "firmware-upgrade/p4-1.x",
        template_id_prefix: str = "p4_1_x_fw_upgrade_v",
        source_branch: str = "main",
        presigned_role_arn: str = (
            "arn:aws:iam::303188940251:role/iot-jobs-firmware-manifest-read-role"
        ),
        timeout_minutes: int = 15,
    ) -> tuple[subprocess.CompletedProcess[str], str | None]:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "iot-job-template-request.json"
            command = [
                "python3",
                str(SCRIPT),
                "render",
                "--vehicle-type",
                vehicle_type,
                "--version",
                version,
                "--bucket",
                bucket,
                "--region",
                region,
                "--key-prefix",
                key_prefix,
                "--template-id-prefix",
                template_id_prefix,
                "--source-branch",
                source_branch,
                "--presigned-url-role-arn",
                presigned_role_arn,
                "--timeout-minutes",
                str(timeout_minutes),
                "--output",
                str(output_path),
            ]

            result = subprocess.run(
                command,
                cwd=ROOT,
                text=True,
                capture_output=True,
            )

            if result.returncode == 0:
                return result, output_path.read_text(encoding="utf-8")

            return result, None

    def run_compare(
        self,
        *,
        expected: dict,
        actual: dict,
    ) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            expected_path = temp_path / "expected.json"
            actual_path = temp_path / "actual.json"
            expected_path.write_text(json.dumps(expected), encoding="utf-8")
            actual_path.write_text(json.dumps(actual), encoding="utf-8")

            return subprocess.run(
                [
                    "python3",
                    str(SCRIPT),
                    "compare",
                    "--expected-file",
                    str(expected_path),
                    "--actual-file",
                    str(actual_path),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
            )

    def test_render_builds_expected_template_request(self):
        result, output_text = self.run_render()

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIsNotNone(output_text)

        data = json.loads(output_text)
        self.assertEqual(data["jobTemplateId"], "p4_1_x_fw_upgrade_v1_3_1")
        self.assertEqual(data["description"], "P4-1.X firmware-upgrade manifest v1.3.1")
        self.assertEqual(
            data["documentSource"],
            "https://vehicle-iot-manifest-update-dev-303188940251.s3.eu-central-1.amazonaws.com/firmware-upgrade/p4-1.x/1.3.1.json",
        )
        self.assertEqual(
            data["presignedUrlConfig"]["roleArn"],
            "arn:aws:iam::303188940251:role/iot-jobs-firmware-manifest-read-role",
        )
        self.assertEqual(
            data["timeoutConfig"]["inProgressTimeoutInMinutes"],
            15,
        )
        self.assertEqual(
            data["tags"],
            [
                {"Key": "operation", "Value": "firmware-upgrade"},
                {"Key": "vehicleType", "Value": "P4-1.X"},
                {"Key": "manifestVersion", "Value": "v1.3.1"},
                {"Key": "sourceBranch", "Value": "main"},
                {
                    "Key": "s3Key",
                    "Value": "firmware-upgrade/p4-1.x/1.3.1.json",
                },
            ],
        )

    def test_render_sanitizes_dev_versions_for_template_id(self):
        result, output_text = self.run_render(version="1.3.1-dev1")

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIsNotNone(output_text)
        data = json.loads(output_text)
        self.assertEqual(data["jobTemplateId"], "p4_1_x_fw_upgrade_v1_3_1_dev1")
        self.assertEqual(data["documentSource"], "https://vehicle-iot-manifest-update-dev-303188940251.s3.eu-central-1.amazonaws.com/firmware-upgrade/p4-1.x/1.3.1-dev1.json")

    def test_render_fails_on_invalid_timeout(self):
        result, _ = self.run_render(timeout_minutes=0)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("timeout-minutes must be between 1 and 10080", result.stderr)

    def test_compare_succeeds_for_matching_describe_output(self):
        expected = {
            "jobTemplateId": "p4_1_x_fw_upgrade_v1_3_1",
            "description": "P4-1.X firmware-upgrade manifest v1.3.1",
            "documentSource": "https://example.com/firmware-upgrade/p4-1.x/1.3.1.json",
            "presignedUrlConfig": {
                "roleArn": "arn:aws:iam::303188940251:role/iot-jobs-firmware-manifest-read-role"
            },
            "timeoutConfig": {"inProgressTimeoutInMinutes": 15},
            "tags": [{"Key": "operation", "Value": "firmware-upgrade"}],
        }
        actual = {
            "jobTemplateArn": "arn:aws:iot:eu-central-1:303188940251:jobtemplate/p4_1_x_fw_upgrade_v1_3_1",
            "jobTemplateId": "p4_1_x_fw_upgrade_v1_3_1",
            "description": "P4-1.X firmware-upgrade manifest v1.3.1",
            "documentSource": "https://example.com/firmware-upgrade/p4-1.x/1.3.1.json",
            "presignedUrlConfig": {
                "roleArn": "arn:aws:iam::303188940251:role/iot-jobs-firmware-manifest-read-role"
            },
            "timeoutConfig": {"inProgressTimeoutInMinutes": 15},
            "createdAt": "2026-04-14T10:00:00Z",
        }

        result = self.run_compare(expected=expected, actual=actual)

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("matches expected request", result.stdout)

    def test_compare_fails_for_mismatched_document_source(self):
        expected = {
            "jobTemplateId": "p4_1_x_fw_upgrade_v1_3_1",
            "description": "P4-1.X firmware-upgrade manifest v1.3.1",
            "documentSource": "https://example.com/firmware-upgrade/p4-1.x/1.3.1.json",
            "presignedUrlConfig": {"roleArn": "arn:aws:iam::303188940251:role/example"},
            "timeoutConfig": {"inProgressTimeoutInMinutes": 15},
        }
        actual = {
            "jobTemplateId": "p4_1_x_fw_upgrade_v1_3_1",
            "description": "P4-1.X firmware-upgrade manifest v1.3.1",
            "documentSource": "https://example.com/firmware-upgrade/p4-1.x/1.3.2.json",
            "presignedUrlConfig": {"roleArn": "arn:aws:iam::303188940251:role/example"},
            "timeoutConfig": {"inProgressTimeoutInMinutes": 15},
        }

        result = self.run_compare(expected=expected, actual=actual)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("documentSource mismatch", result.stderr)


if __name__ == "__main__":
    unittest.main()
