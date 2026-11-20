import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from dev_build import DevVersionError, dev_build, main  # noqa: E402


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


class Repo:
    """main and develop as TCUStack uses them: every pull request bumps balena.yml,
    develop releases to main through a merge commit that is tagged there and never
    merged back."""

    def __init__(self, root: Path):
        self.path = root
        git(root, "init", "-q", "-b", "main")
        git(root, "config", "user.email", "ci@example.com")
        git(root, "config", "user.name", "CI")
        git(root, "config", "commit.gpgsign", "false")
        git(root, "config", "tag.gpgsign", "false")

    def commit(self, version: str, subject: str = "change") -> str:
        (self.path / "balena.yml").write_text(f'type: sw.application\nversion: "{version}"\n')
        git(self.path, "add", "balena.yml")
        git(self.path, "commit", "-q", "--allow-empty", "-m", subject)
        return git(self.path, "rev-parse", "HEAD")

    def merge(self, branch: str, subject: str) -> str:
        git(self.path, "merge", "-q", "--no-ff", "-m", subject, branch)
        return git(self.path, "rev-parse", "HEAD")

    def checkout(self, branch: str, create: bool = False) -> None:
        git(self.path, "checkout", "-q", *(["-b"] if create else []), branch)

    def release(self, version: str) -> None:
        """Merge develop into main and tag the merge commit, as the release PR does."""
        self.checkout("main")
        self.merge("develop", f"Release {version}")
        git(self.path, "tag", f"TCU_STACK_v{version}")
        self.checkout("develop")


class DevBuildTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = Repo(Path(self._tmp.name))
        self.repo.commit("1.0.0", "initial")
        git(self.repo.path, "tag", "TCU_STACK_v1.0.0")
        self.repo.checkout("develop", create=True)

    def tearDown(self):
        self._tmp.cleanup()

    def version(self, commit: str = "HEAD") -> dict:
        return dev_build(self.repo.path, "TCU_STACK_v", commit=commit)

    def test_version_comes_from_balena_yml_and_build_from_depth(self):
        self.repo.commit("1.0.1", "bump")
        values = self.version()
        self.assertEqual(values["version"], "1.0.1-dev2")
        self.assertEqual(values["version_tag"], "TCU_STACK_v1.0.1-dev2")
        self.assertEqual(values["dev_tag"], "dev/TCU_STACK_v1.0.1-dev2")
        self.assertEqual(values["build"], "2")

    def test_every_develop_merge_gets_its_own_number(self):
        seen = []
        for i, bump in enumerate(["1.0.1", "1.0.2", "1.1.0", "1.1.1"]):
            self.repo.checkout(f"feature/{i}", create=True)
            self.repo.commit(bump, f"feature {i}")
            self.repo.checkout("develop")
            self.repo.merge(f"feature/{i}", f"Merge feature {i}")
            seen.append(self.version()["version"])
        # Only the merge commits lie on develop's first-parent line.
        self.assertEqual(seen, ["1.0.1-dev2", "1.0.2-dev3", "1.1.0-dev4", "1.1.1-dev5"])

    def test_release_on_main_not_merged_back_still_numbers_the_next_version(self):
        # TCUStack never merges main back: the release tag sits on main's merge
        # commit, and develop carries on from the bumped balena.yml.
        self.repo.commit("1.0.1", "work")
        self.repo.release("1.0.1")
        self.repo.commit("1.0.2", "next")
        self.assertEqual(self.version()["version"], "1.0.2-dev3")

    def test_balena_yml_not_above_the_latest_release_is_refused(self):
        self.repo.commit("1.0.1", "work")
        self.repo.release("1.0.1")
        self.repo.commit("1.0.1", "forgot to bump")
        with self.assertRaisesRegex(DevVersionError, "TCU_STACK_v1.0.1 is not merged back"):
            self.version()

    def test_release_commit_is_not_a_dev_build(self):
        self.repo.checkout("main")
        with self.assertRaisesRegex(DevVersionError, "is the release"):
            self.version()

    def test_missing_version_line_is_refused(self):
        (self.repo.path / "balena.yml").write_text("type: sw.application\n")
        git(self.repo.path, "commit", "-q", "-am", "no version")
        with self.assertRaisesRegex(DevVersionError, "no 'version: X.Y.Z' line"):
            self.version()

    def test_main_writes_github_output(self):
        self.repo.commit("1.0.1", "bump")
        with tempfile.NamedTemporaryFile("r", delete=False) as output:
            os.environ["GITHUB_OUTPUT"] = output.name
            try:
                rc = main(["--tag-prefix", "TCU_STACK_v", "--repo", str(self.repo.path), "--github-output"])
            finally:
                del os.environ["GITHUB_OUTPUT"]
            self.assertEqual(rc, 0)
            self.assertIn("dev_tag=dev/TCU_STACK_v1.0.1-dev2\n", Path(output.name).read_text())
        os.unlink(output.name)


if __name__ == "__main__":
    unittest.main()
