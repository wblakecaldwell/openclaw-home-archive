"""Unit tests for scripts/manage_directives.py."""

from pathlib import Path
import tempfile
import unittest

from scripts.manage_directives import (
    START_MARKER,
    END_MARKER,
    extract_managed_block,
    install_directives,
    remove_directives,
    check_directives,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CANONICAL_SOURCE = PROJECT_ROOT / "openclaw/main-routing-instructions.md"


class ManageDirectivesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.tmp_dir = Path(self.tmp.name)
        self.target_file = self.tmp_dir / "AGENTS.md"

    def test_extract_managed_block_from_canonical_source(self):
        block = extract_managed_block(CANONICAL_SOURCE)
        self.assertTrue(block.startswith(START_MARKER))
        self.assertTrue(block.endswith(END_MARKER))
        self.assertIn("archivist", block)
        self.assertIn("sessions_spawn", block)

    def test_install_fresh_target_file(self):
        self.assertFalse(self.target_file.exists())
        msg = install_directives(self.target_file, CANONICAL_SOURCE)
        self.assertIn("Created", msg)
        self.assertTrue(self.target_file.exists())
        content = self.target_file.read_text(encoding="utf-8")
        self.assertTrue(content.startswith(START_MARKER))
        self.assertTrue(content.strip().endswith(END_MARKER))
        self.assertTrue(check_directives(self.target_file))

    def test_install_append_to_existing_file_without_markers(self):
        initial = "# Custom Main Directives\n\n- Be polite.\n"
        self.target_file.write_text(initial, encoding="utf-8")

        msg = install_directives(self.target_file, CANONICAL_SOURCE)
        self.assertIn("Appended", msg)

        content = self.target_file.read_text(encoding="utf-8")
        self.assertTrue(content.startswith("# Custom Main Directives\n\n- Be polite.\n\n" + START_MARKER))
        self.assertTrue(content.strip().endswith(END_MARKER))
        self.assertTrue(check_directives(self.target_file))

    def test_update_existing_block_preserves_surrounding_text(self):
        before = "# Header Section\n\nRule 1.\n"
        old_block = f"{START_MARKER}\nOld obsolete instructions\n{END_MARKER}"
        after = "## Footer Section\n\nRule 2.\n"
        self.target_file.write_text(f"{before}\n{old_block}\n\n{after}", encoding="utf-8")

        msg = install_directives(self.target_file, CANONICAL_SOURCE)
        self.assertIn("Updated", msg)

        content = self.target_file.read_text(encoding="utf-8")
        self.assertTrue(content.startswith("# Header Section\n\nRule 1.\n\n" + START_MARKER))
        self.assertIn("sessions_spawn", content)
        self.assertNotIn("Old obsolete instructions", content)
        self.assertTrue(content.endswith("## Footer Section\n\nRule 2.\n"))
        self.assertTrue(check_directives(self.target_file))

    def test_install_is_idempotent(self):
        install_directives(self.target_file, CANONICAL_SOURCE)
        first_pass = self.target_file.read_text(encoding="utf-8")

        install_directives(self.target_file, CANONICAL_SOURCE)
        second_pass = self.target_file.read_text(encoding="utf-8")

        self.assertEqual(first_pass, second_pass)

    def test_remove_directives_preserves_surrounding_text(self):
        before = "# Header Section\n\nRule 1."
        block = extract_managed_block(CANONICAL_SOURCE)
        after = "## Footer Section\n\nRule 2."
        self.target_file.write_text(f"{before}\n\n{block}\n\n{after}\n", encoding="utf-8")

        msg = remove_directives(self.target_file)
        self.assertIn("Removed", msg)

        content = self.target_file.read_text(encoding="utf-8")
        self.assertEqual(content, f"{before}\n\n{after}\n")
        self.assertFalse(check_directives(self.target_file))

    def test_remove_directives_when_only_directives_present(self):
        install_directives(self.target_file, CANONICAL_SOURCE)
        remove_directives(self.target_file)
        content = self.target_file.read_text(encoding="utf-8")
        self.assertEqual(content, "")
        self.assertFalse(check_directives(self.target_file))

    def test_remove_when_not_present_is_noop(self):
        initial = "# Unrelated file\n"
        self.target_file.write_text(initial, encoding="utf-8")
        msg = remove_directives(self.target_file)
        self.assertIn("No Personal Archive routing directives found", msg)
        self.assertEqual(self.target_file.read_text(encoding="utf-8"), initial)

    def test_corrupted_markers_raises_error(self):
        # Missing end marker
        self.target_file.write_text(f"{START_MARKER}\nUnfinished block", encoding="utf-8")
        with self.assertRaises(ValueError):
            install_directives(self.target_file, CANONICAL_SOURCE)

        # Missing start marker
        self.target_file.write_text(f"Unfinished block\n{END_MARKER}", encoding="utf-8")
        with self.assertRaises(ValueError):
            install_directives(self.target_file, CANONICAL_SOURCE)


if __name__ == "__main__":
    unittest.main()
