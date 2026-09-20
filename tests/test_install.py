"""Exercise installation only inside disposable home directories."""

import os
import json
import sys
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


PROJECT = Path(__file__).resolve().parents[1]


class InstallTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="home-archive-install-test-")
        self.addCleanup(temporary.cleanup)
        self.workspace = Path(temporary.name)
        self.user_home = self.workspace / "test home"
        self.destination = self.user_home / ".openclaw/workspace/skills/home-archive"
        self.source = self.workspace / "source checkout"
        (self.source / "scripts").mkdir(parents=True)
        for name in (
            "install.sh",
            "SKILL.md",
            "README.md",
            "scripts/home_archive.py",
            "scripts/setup_archive.py",
        ):
            shutil.copy2(PROJECT / name, self.source / name)
        # HOME is supplied only to the child installer, never changed in this process.
        self.env = dict(
            os.environ,
            HOME=str(self.user_home),
            HOME_ARCHIVE_ROOT=str(self.workspace / "household archive"),
            PYTHONDONTWRITEBYTECODE="1",
        )

        self.config = self.workspace / "openclaw.json"
        self.config.write_text(
            json.dumps(
                {
                    "skills": {
                        "entries": {
                            "home-archive": {
                                "env": {
                                    "HOME_ARCHIVE_ROOT": self.env["HOME_ARCHIVE_ROOT"],
                                }
                            }
                        }
                    },
                    "unrelated": {"keep": True},
                }
            )
        )
        fake_bin = self.workspace / "bin"
        fake_bin.mkdir()
        fake = fake_bin / "openclaw"
        fake.write_text(
            "#!"
            + sys.executable
            + "\n"
            + (PROJECT / "tests/fixtures/openclaw.py").read_text()
        )
        fake.chmod(0o755)
        self.env["PATH"] = str(fake_bin) + os.pathsep + os.environ["PATH"]
        self.env["TEST_OPENCLAW_CONFIG"] = str(self.config)

    def install(self, source=None, success=True, args=()):
        result = subprocess.run(
            ["bash", str((source or self.source) / "install.sh"), *args],
            env=self.env,
            capture_output=True,
            text=True,
            timeout=15,
        )
        if success:
            self.assertEqual(result.returncode, 0, result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0)
        return result

    def test_reinstall_replaces_all_files_without_backups(self):
        self.install()
        (self.destination / ".old-config").write_text("stale")
        (self.destination / "old-subdirectory").mkdir()
        (self.destination / "old-subdirectory/stale.txt").write_text("stale")
        (self.destination / "SKILL.md").write_text("local modification")
        self.install()
        files = {
            str(p.relative_to(self.destination))
            for p in self.destination.rglob("*")
            if p.is_file()
        }
        self.assertEqual(files, {"SKILL.md", "README.md", "scripts/home_archive.py"})
        for name in files:
            self.assertEqual(
                (self.destination / name).read_bytes(),
                (self.source / name).read_bytes(),
            )
        self.assertTrue(
            os.access(self.destination / "scripts/home_archive.py", os.X_OK)
        )
        self.assertEqual(list(self.destination.parent.iterdir()), [self.destination])

    def test_install_leaves_config_and_archive_untouched(self):
        config = self.config
        before = config.read_bytes()
        archive = Path(self.env["HOME_ARCHIVE_ROOT"])
        archive.mkdir()
        evidence = archive / "synthetic.txt"
        evidence.write_bytes(b"Synthetic evidence")
        self.install()
        self.assertEqual(config.read_bytes(), before)
        self.assertEqual(list(archive.iterdir()), [evidence])
        self.assertEqual(evidence.read_bytes(), b"Synthetic evidence")

    def test_existing_config_works_without_shell_variable_or_archive_initialization(
        self,
    ):
        self.env.pop("HOME_ARCHIVE_ROOT")
        self.install()
        self.assertFalse((self.user_home / "Documents").exists())
        self.assertEqual({p.name for p in self.user_home.iterdir()}, {".openclaw"})

    def test_incomplete_source_preserves_previous_install(self):
        self.install()
        previous = (self.destination / "SKILL.md").read_bytes()
        (self.source / "scripts/home_archive.py").unlink()
        self.install(success=False)
        self.assertEqual((self.destination / "SKILL.md").read_bytes(), previous)
        self.assertTrue((self.destination / "scripts/home_archive.py").exists())
        self.assertEqual(list(self.destination.parent.iterdir()), [self.destination])

    def test_replacing_symlink_preserves_its_target(self):
        self.destination.parent.mkdir(parents=True)
        self.destination.symlink_to(self.source, target_is_directory=True)
        self.install()
        self.assertFalse(self.destination.is_symlink())
        self.assertTrue((self.source / "install.sh").exists())
        self.assertEqual(
            (self.destination / "SKILL.md").read_bytes(),
            (self.source / "SKILL.md").read_bytes(),
        )

    def test_source_inside_destination_is_rejected(self):
        self.destination.parent.mkdir(parents=True)
        shutil.copytree(self.source, self.destination)
        result = self.install(source=self.destination, success=False)
        self.assertIn("outside the installed skill directory", result.stderr)
        self.assertTrue((self.destination / "install.sh").exists())

    def test_missing_configuration_requires_explicit_noninteractive_location(self):
        self.config.write_text("{}")
        result = self.install(success=False)
        self.assertIn("--archive-root", result.stderr)
        self.assertFalse(self.destination.exists())
        self.assertEqual(self.config.read_text(), "{}")

    def test_explicit_location_is_persisted_and_displayed(self):
        self.config.write_text('{"unrelated": {"keep": true}}')
        location = str(self.workspace / 'archive with spaces "and quotes"')
        result = self.install(args=("--archive-root", location))
        data = json.loads(self.config.read_text())
        self.assertTrue(data["unrelated"]["keep"])
        self.assertEqual(
            data["skills"]["entries"]["home-archive"]["env"]["HOME_ARCHIVE_ROOT"],
            location,
        )
        self.assertIn(location, result.stdout)
        self.assertFalse(Path(location).exists())

    def test_existing_location_is_displayed_and_preserved(self):
        before = self.config.read_bytes()
        self.env["HOME_ARCHIVE_ROOT"] = str(self.workspace / "temporary override")
        result = self.install()
        self.assertIn("existing OpenClaw configuration", result.stdout)
        self.assertIn("shell HOME_ARCHIVE_ROOT differs", result.stdout)
        self.assertEqual(self.config.read_bytes(), before)

    def test_conflicting_location_is_rejected(self):
        before = self.config.read_bytes()
        self.install(
            args=("--archive-root", str(self.workspace / "other")), success=False
        )
        self.assertEqual(self.config.read_bytes(), before)
        self.assertFalse(self.destination.exists())

    def test_config_errors_do_not_replace_installed_code(self):
        self.install()
        marker = self.destination / "preserve.txt"
        marker.write_text("Existing installation")
        self.env["TEST_OPENCLAW_READ_FAILURE"] = "1"
        self.install(success=False)
        self.assertTrue(marker.exists())
        self.env.pop("TEST_OPENCLAW_READ_FAILURE")
        self.config.write_text("{}")
        self.env["TEST_OPENCLAW_WRITE_FAILURE"] = "1"
        self.install(
            args=("--archive-root", str(self.workspace / "archive")), success=False
        )
        self.assertTrue(marker.exists())
        self.assertEqual(self.config.read_text(), "{}")

    def test_invalid_locations_are_rejected_before_replacement(self):
        self.config.write_text("{}")
        for location in (
            "",
            " ",
            "relative/path",
            "<archive-root>",
            str(self.destination / "data"),
        ):
            with self.subTest(location=location):
                self.install(args=("--archive-root", location), success=False)
                self.assertFalse(self.destination.exists())
                self.assertEqual(self.config.read_text(), "{}")
