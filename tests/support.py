"""Shared isolation for direct function and subprocess CLI tests."""

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "home_archive.py"


class ArchiveTestCase(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="home-archive-test-")
        self.addCleanup(temporary.cleanup)
        self.workspace = Path(temporary.name)
        self.root = self.workspace / "archive"
        self.env = dict(os.environ, HOME_ARCHIVE_ROOT=str(self.root))

        # Configure a fresh module so every derived path uses this test's archive.
        with patch.dict(os.environ, {"HOME_ARCHIVE_ROOT": str(self.root)}):
            spec = importlib.util.spec_from_file_location("archive_under_test", SCRIPT)
            self.archive = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(self.archive)
            self.archive.configure_root()

        # Fail closed: even an unexpected Photos call cannot launch osascript.
        guard = patch.object(
            self.archive,
            "osa",
            side_effect=AssertionError("Real Photos access forbidden"),
        )
        self.osa = guard.start()
        self.addCleanup(guard.stop)
        clock = patch.object(self.archive, "today", return_value="2026-09-20")
        clock.start()
        self.addCleanup(clock.stop)

    def source(self, name="evidence.txt", content=b"Synthetic evidence"):
        path = self.workspace / name
        path.write_bytes(content)
        return path

    def create_record(self, **fields):
        return self.archive.create({"title": "TestCo toaster", **fields})["record"]

    def events(self, entity):
        path = self.archive.rdir(entity) / "events.jsonl"
        return [json.loads(line) for line in path.read_text().splitlines()]

    def snapshot(self):
        return {
            str(path.relative_to(self.root)): path.read_bytes()
            for path in self.root.rglob("*")
            if path.is_file()
        }

    def cli(self, *args, ok=True):
        # Only these commands are allowed in real subprocesses; Photos and doctor
        # are exercised in-process with mocked external boundaries instead.
        self.assertIn(
            args[0],
            {
                "init",
                "create",
                "add",
                "show",
                "search",
                "get-attachment",
                "set-fact",
                "remove-fact",
                "remove-attachment",
                "delete",
                "merge",
            },
        )
        result = subprocess.run(
            [sys.executable, str(SCRIPT), *map(str, args)],
            env=self.env,
            capture_output=True,
            text=True,
            timeout=15,
        )
        self.assertEqual(result.stderr, "")
        response = json.loads(result.stdout)
        self.assertIs(response["ok"], ok, response)
        if ok:
            self.assertEqual(result.returncode, 0, response)
        else:
            self.assertNotEqual(result.returncode, 0, response)
        return response
