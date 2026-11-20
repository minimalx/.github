import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "collect_submodules.py"


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


class Board:
    """A board repo checked out where the manifest's .gitmodules says it is."""

    def __init__(self, path: Path):
        self.path = path
        path.mkdir(parents=True)
        git(path, "init", "-q", "-b", "develop")
        git(path, "config", "user.email", "ci@example.com")
        git(path, "config", "user.name", "CI")
        git(path, "config", "commit.gpgsign", "false")
        git(path, "config", "tag.gpgsign", "false")
        self.n = 0

    def commit(self) -> str:
        self.n += 1
        (self.path / "f.txt").write_text(str(self.n))
        git(self.path, "add", "f.txt")
        git(self.path, "commit", "-q", "-m", f"c{self.n}")
        return git(self.path, "rev-parse", "HEAD")

    def tag(self, *names: str) -> None:
        for name in names:
            git(self.path, "tag", name)


class CollectSubmodulesTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / ".gitmodules").write_text(
            '[submodule "body-control-unit"]\n\tpath = body-control-unit\n'
            '[submodule "hmi"]\n\tpath = hmi\n'
            '[submodule "workflow-templates"]\n\tpath = workflow-templates\n'
        )
        self.bcu = Board(self.root / "body-control-unit")
        self.hmi = Board(self.root / "hmi")
        self.hmi.commit()
        self.hmi.tag("v0.3.11")
        # A released BCU, then one develop merge built as a dev build.
        self.bcu.commit()
        self.bcu.tag("BCU_APP_v4.4.8", "BCU_BL_v2.2.11")
        self.bcu.commit()
        self.bcu.tag("dev/BCU_APP_v4.4.9-dev98", "dev/BCU_BL_v2.2.12-dev98")

    def tearDown(self):
        self._tmp.cleanup()

    def collect(self, *args: str) -> dict[str, str]:
        result = subprocess.run(
            [sys.executable, str(SCRIPT), *args], cwd=self.root, capture_output=True, text=True
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        lines = (self.root / "submodule_versions.txt").read_text().splitlines()
        return {line.split(" ", 1)[0]: line.split(" ", 1)[1] for line in lines}

    def test_release_ignores_dev_tags(self):
        # Pinned at the dev build: no release app version (the generator then
        # fails), and the bootloader is the last release, never the dev build.
        versions = self.collect()
        self.assertEqual(versions["body-control-unit"], " 2.2.11")
        self.assertEqual(versions["hmi"], "0.3.11")
        self.assertNotIn("workflow-templates", versions)

    def test_release_is_the_default_channel(self):
        self.assertEqual(self.collect(), self.collect("--channel", "release"))

    def test_release_reads_release_tags(self):
        git(self.bcu.path, "checkout", "-q", "BCU_APP_v4.4.8")
        self.assertEqual(self.collect()["body-control-unit"], "4.4.8 2.2.11")

    def test_release_refuses_a_suffixed_version(self):
        self.bcu.commit()
        self.bcu.tag("BCU_APP_v4.4.9-rc1")
        self.assertEqual(self.collect()["body-control-unit"], " 2.2.11")

    def test_development_reads_dev_tags_with_their_suffix(self):
        versions = self.collect("--channel", "development")
        self.assertEqual(versions["body-control-unit"], "4.4.9-dev98 2.2.12-dev98")
        self.assertEqual(versions["hmi"], "0.3.11")

    def test_development_prefers_a_release_tag(self):
        git(self.bcu.path, "checkout", "-q", "BCU_APP_v4.4.8")
        self.assertEqual(
            self.collect("--channel", "development")["body-control-unit"], "4.4.8 2.2.11"
        )

    def test_development_bootloader_falls_back_to_the_nearest_build(self):
        # The next merge changed only the app: its bootloader is still dev98's.
        self.bcu.commit()
        self.bcu.tag("dev/BCU_APP_v4.4.9-dev99")
        self.assertEqual(
            self.collect("--channel", "development")["body-control-unit"],
            "4.4.9-dev99 2.2.12-dev98",
        )

    def test_unknown_channel_fails(self):
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--channel", "prod"],
            cwd=self.root, capture_output=True, text=True,
        )
        self.assertNotEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
