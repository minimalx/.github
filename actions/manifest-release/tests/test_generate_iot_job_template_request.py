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
        document_source_style: str = "virtual-hosted",
        inline_document_body=None,
        timeout_minutes: int = 15,
    ) -> tuple[subprocess.CompletedProcess[str], str | None]:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            output_path = temp_path / "iot-job-template-request.json"
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
                "--document-source-style",
                document_source_style,
                "--timeout-minutes",
                str(timeout_minutes),
                "--output",
                str(output_path),
            ]

            if inline_document_body is not None:
                document_path = temp_path / "manifest.json"
                document_path.write_text(
                    json.dumps(inline_document_body, indent=2),
                    encoding="utf-8",
                )
                command.extend(["--inline-document-file", str(document_path)])

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

    def test_render_builds_expected_inline_template_request(self):
        manifest = {
            "operation": "firmware-upgrade",
            "manifestVersion": "v1.3.1",
            "vehicleType": "P4-2.X",
            "boards": {"BCU": {"app": "1.0.0", "boot": "1.0.1"}},
        }

        result, output_text = self.run_render(inline_document_body=manifest)

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIsNotNone(output_text)

        data = json.loads(output_text)
        self.assertEqual(data["jobTemplateId"], "p4_1_x_fw_upgrade_v1_3_1")
        self.assertEqual(data["description"], "P4-1.X firmware-upgrade manifest v1.3.1")
        self.assertEqual(
            data["document"],
            json.dumps(manifest, separators=(",", ":"), sort_keys=True),
        )
        self.assertNotIn("documentSource", data)
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

    def test_render_supports_legacy_document_source_requests(self):
        result, output_text = self.run_render()

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIsNotNone(output_text)
        data = json.loads(output_text)
        self.assertEqual(
            data["documentSource"],
            "https://vehicle-iot-manifest-update-dev-303188940251.s3.eu-central-1.amazonaws.com/firmware-upgrade/p4-1.x/1.3.1.json",
        )

    def test_render_sanitizes_dev_versions_for_template_id(self):
        result, output_text = self.run_render(
            version="1.3.1-dev1",
            inline_document_body={"operation": "firmware-upgrade"},
        )

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIsNotNone(output_text)
        data = json.loads(output_text)
        self.assertEqual(data["jobTemplateId"], "p4_1_x_fw_upgrade_v1_3_1_dev1")
        self.assertNotIn("documentSource", data)

    def test_render_fails_on_invalid_timeout(self):
        result, _ = self.run_render(timeout_minutes=0)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("timeout-minutes must be between 1 and 10080", result.stderr)

    def test_render_fails_when_inline_document_is_too_large(self):
        result, _ = self.run_render(
            inline_document_body={"payload": "x" * 40000},
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Inline document exceeds AWS IoT limit", result.stderr)

    def test_compare_succeeds_for_matching_document_source_output(self):
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

    def test_compare_succeeds_for_matching_inline_document_with_different_formatting(self):
        expected = {
            "jobTemplateId": "p4_2_x_fw_upgrade_v1_3_1",
            "description": "P4-2.X firmware-upgrade manifest v1.3.1",
            "document": "{\"boards\":{\"BCU\":{\"app\":\"1.0.0\",\"boot\":\"1.0.1\"}},\"operation\":\"firmware-upgrade\"}",
            "presignedUrlConfig": {
                "roleArn": "arn:aws:iam::303188940251:role/iot-jobs-firmware-manifest-read-role"
            },
            "timeoutConfig": {"inProgressTimeoutInMinutes": 15},
        }
        actual = {
            "jobTemplateId": "p4_2_x_fw_upgrade_v1_3_1",
            "description": "P4-2.X firmware-upgrade manifest v1.3.1",
            "document": json.dumps(
                {
                    "operation": "firmware-upgrade",
                    "boards": {"BCU": {"boot": "1.0.1", "app": "1.0.0"}},
                },
                indent=2,
            ),
            "presignedUrlConfig": {
                "roleArn": "arn:aws:iam::303188940251:role/iot-jobs-firmware-manifest-read-role"
            },
            "timeoutConfig": {"inProgressTimeoutInMinutes": 15},
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

    def test_compare_fails_for_mismatched_inline_document_content(self):
        expected = {
            "jobTemplateId": "p4_2_x_fw_upgrade_v1_3_1",
            "description": "P4-2.X firmware-upgrade manifest v1.3.1",
            "document": "{\"operation\":\"firmware-upgrade\",\"version\":\"1.3.1\"}",
            "presignedUrlConfig": {"roleArn": "arn:aws:iam::303188940251:role/example"},
            "timeoutConfig": {"inProgressTimeoutInMinutes": 15},
        }
        actual = {
            "jobTemplateId": "p4_2_x_fw_upgrade_v1_3_1",
            "description": "P4-2.X firmware-upgrade manifest v1.3.1",
            "document": "{\"operation\":\"firmware-upgrade\",\"version\":\"1.3.2\"}",
            "presignedUrlConfig": {"roleArn": "arn:aws:iam::303188940251:role/example"},
            "timeoutConfig": {"inProgressTimeoutInMinutes": 15},
        }

        result = self.run_compare(expected=expected, actual=actual)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("document mismatch", result.stderr)


if __name__ == "__main__":
    unittest.main()
