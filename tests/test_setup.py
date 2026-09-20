"""Interactive location selection without a terminal or a live OpenClaw instance."""

import importlib.util
import io
import os
import unittest
from unittest.mock import patch

from tests.support import SCRIPT

spec = importlib.util.spec_from_file_location(
    "setup_archive", SCRIPT.with_name("setup_archive.py")
)
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)


class SetupTests(unittest.TestCase):
    def test_saved_location_must_be_verified(self):
        from types import SimpleNamespace

        with (
            patch.object(setup, "read_root", side_effect=[None, "/synthetic/other"]),
            patch.object(
                setup.subprocess, "run", return_value=SimpleNamespace(returncode=0)
            ),
        ):
            with self.assertRaisesRegex(ValueError, "did not return the saved"):
                setup.configure("/synthetic/archive", "/synthetic/skill")

    def choose(self, answers, candidate=None):
        from types import SimpleNamespace

        root = "/synthetic/archive"
        with patch.dict(os.environ, {}, clear=True):
            if candidate is not None:
                os.environ["HOME_ARCHIVE_ROOT"] = candidate
            with (
                patch.object(setup, "read_root", side_effect=[None, root]),
                patch.object(setup.sys.stdin, "isatty", return_value=True),
                patch("builtins.input", side_effect=answers) as prompt,
                patch.object(
                    setup.subprocess, "run", return_value=SimpleNamespace(returncode=0)
                ) as command,
                patch("sys.stdout", new_callable=io.StringIO),
            ):
                self.assertEqual(setup.configure(None, "/synthetic/skill"), root)
                self.assertIn('"/synthetic/archive"', command.call_args.args[0])
                return prompt.call_args_list

    def test_prompt_without_default(self):
        calls = self.choose(["/synthetic/archive"])
        self.assertEqual(len(calls), 1)
        self.assertIn("no default", calls[0].args[0])

    def test_shell_candidate_requires_acceptance(self):
        calls = self.choose(["yes"], "/synthetic/archive")
        self.assertIn("[y/N]", calls[0].args[0])

    def test_declined_shell_candidate_prompts_for_location(self):
        calls = self.choose(["", "/synthetic/archive"], "/synthetic/temporary")
        self.assertEqual(len(calls), 2)

    def test_blank_response_does_not_write(self):
        with (
            patch.object(setup, "read_root", return_value=None),
            patch.dict(os.environ, {}, clear=True),
            patch.object(setup.sys.stdin, "isatty", return_value=True),
            patch("builtins.input", return_value=""),
            patch.object(setup.subprocess, "run") as command,
        ):
            with self.assertRaises(ValueError):
                setup.configure(None, "/synthetic/skill")
            command.assert_not_called()
