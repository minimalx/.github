import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dev_version import DevVersionError, dev_version  # noqa: E402


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


class Repo:
    """main and develop as the board repos use them."""

    def __init__(self, root: Path):
        self.path = root
        git(root, "init", "-q", "-b", "main")
        git(root, "config", "user.email", "ci@example.com")
        git(root, "config", "user.name", "CI")
        git(root, "config", "commit.gpgsign", "false")
        git(root, "config", "tag.gpgsign", "false")
        self.n = 0

    def commit(self, subject: str = "change") -> str:
        self.n += 1
        (self.path / "f.txt").write_text(str(self.n))
        git(self.path, "add", "f.txt")
        git(self.path, "commit", "-q", "-m", subject)
        return git(self.path, "rev-parse", "HEAD")

    def merge(self, branch: str, subject: str) -> str:
        git(self.path, "merge", "-q", "--no-ff", "-m", subject, branch)
        return git(self.path, "rev-parse", "HEAD")

    def checkout(self, branch: str, create: bool = False) -> None:
        git(self.path, "checkout", "-q", *(["-b"] if create else []), branch)

    def tag(self, name: str, rev: str = "HEAD") -> None:
        git(self.path, "tag", name, rev)


class DevVersionTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = Repo(Path(self._tmp.name))
        self.repo.commit("initial")
        self.repo.tag("BCU_APP_v1.0.0")
        self.repo.checkout("develop", create=True)

    def tearDown(self):
        self._tmp.cleanup()

    def version(self, base: str = "1.0.1", commit: str = "HEAD") -> dict:
        return dev_version(self.repo.path, "BCU_APP_v", base, commit)

    def test_every_develop_merge_gets_its_own_build_number(self):
        seen = set()
        for i in range(4):
            self.repo.checkout(f"feature/{i}", create=True)
            self.repo.commit(f"feature {i}")
            self.repo.commit(f"feature {i} fixup")
            self.repo.checkout("develop")
            self.repo.merge(f"feature/{i}", f"Merge feature {i}")
            seen.add(self.version()["version"])
        self.assertEqual(seen, {"1.0.1-dev1", "1.0.1-dev2", "1.0.1-dev3", "1.0.1-dev4"})

    def test_same_commit_gives_the_same_version(self):
        self.repo.commit()
        self.assertEqual(self.version(), self.version())

    def test_outputs_and_dev_tag_namespace(self):
        self.repo.commit()
        values = self.version()
        self.assertEqual(values["version"], "1.0.1-dev1")
        self.assertEqual(values["version_tag"], "BCU_APP_v1.0.1-dev1")
        self.assertEqual(values["dev_tag"], "dev/BCU_APP_v1.0.1-dev1")
        self.assertEqual(values["build"], "1")

    def test_release_not_merged_back_is_refused(self):
        self.repo.commit("work for 1.0.1")
        self.repo.checkout("main")
        self.repo.merge("develop", "Release")
        self.repo.tag("BCU_APP_v1.0.1")
        self.repo.checkout("develop")
        self.repo.commit("more work")
        with self.assertRaisesRegex(DevVersionError, "BCU_APP_v1.0.1 is not merged back"):
            self.version(base="1.0.1")

    def test_release_merged_back_counts_from_it(self):
        self.repo.commit("work for 1.0.1")
        self.repo.checkout("main")
        self.repo.merge("develop", "Release")
        self.repo.tag("BCU_APP_v1.0.1")
        self.repo.checkout("develop")
        self.repo.merge("main", "Back-merge main")
        self.repo.commit("next work")
        self.assertEqual(self.version(base="1.0.2")["version"], "1.0.2-dev2")

    def test_dev_tags_and_other_prefixes_are_not_releases(self):
        self.repo.commit()
        self.repo.tag("dev/BCU_APP_v9.9.9-dev1")
        self.repo.tag("BCU_APP_v9.9.9-dev1")
        self.repo.tag("BCU_BL_v9.9.9")
        self.repo.commit()
        self.assertEqual(self.version()["version"], "1.0.1-dev2")

    def test_release_commit_is_not_a_dev_build(self):
        self.repo.checkout("main")
        with self.assertRaisesRegex(DevVersionError, "is the release"):
            self.version(base="1.0.0")

    def test_no_release_tag_counts_whole_first_parent_history(self):
        git(self.repo.path, "tag", "-d", "BCU_APP_v1.0.0")
        self.repo.commit()
        self.assertEqual(self.version(base="0.0.1")["version"], "0.0.1-dev2")

    def test_shallow_history_is_refused(self):
        self.repo.commit()
        with tempfile.TemporaryDirectory() as shallow:
            subprocess.run(
                ["git", "clone", "-q", "--depth", "1", "--branch", "develop",
                 f"file://{self.repo.path}", shallow],
                check=True, capture_output=True,
            )
            with self.assertRaisesRegex(DevVersionError, "shallow"):
                dev_version(Path(shallow), "BCU_APP_v", "1.0.1")

    def test_bad_base_is_refused(self):
        with self.assertRaisesRegex(DevVersionError, "not X.Y.Z"):
            self.version(base="1.0.1-dev3")


if __name__ == "__main__":
    unittest.main()
