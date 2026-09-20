import json
from pathlib import Path

from tests.support import ArchiveTestCase


class CLITests(ArchiveTestCase):
    def write_spec(self, value):
        path = self.workspace / "spec.json"
        path.write_text(json.dumps(value))
        return path

    def test_create_show_search_and_attachment_use_returned_ids(self):
        source = self.source()
        spec = self.write_spec(
            {
                "title": "TestCo toaster",
                "event_date": "2026-09-20",
                "attachments": [{"path": str(source)}],
            }
        )
        result = self.cli("create", "--spec", spec)
        entity = result["record"]["id"]
        self.assertRegex(entity, r"^HA-\d{8}-\d{4}$")
        persisted = json.loads(
            (self.root / "records" / entity / "metadata.json").read_text()
        )
        self.assertEqual(self.cli("show", entity)["record"], persisted)
        self.assertEqual(self.cli("search", "TestCo")["results"][0]["id"], entity)
        aid = result["attachments_added"][0]["id"]
        attachment = self.cli("get-attachment", aid)
        path = Path(attachment["path"])
        self.assertEqual(path.parent, self.root / "records" / entity / "attachments")
        self.assertEqual(path.read_bytes(), source.read_bytes())

    def test_repaired_spec_requires_actual_rerun(self):
        self.cli("init")
        before = self.snapshot()
        spec = self.workspace / "spec.json"
        spec.write_text("{invalid")
        failure = self.cli("create", "--spec", spec, ok=False)
        self.assertIn("error", failure)
        self.assertEqual(self.snapshot(), before)
        self.write_spec({"title": "TestCo toaster"})
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.cli("search", "TestCo")["results"], [])
        result = self.cli("create", "--spec", spec)
        self.assertTrue(
            (self.root / "records" / result["record"]["id"] / "metadata.json").exists()
        )

    def test_nonexistent_identifiers_fail(self):
        for args in (
            ("show", "HA-19990101-9999"),
            ("get-attachment", "HAA-19990101-9999"),
            ("delete", "HA-19990101-9999"),
        ):
            with self.subTest(args=args):
                self.assertIn("error", self.cli(*args, ok=False))

    def test_missing_fact_returns_failure_exit_status(self):
        result = self.cli("create", "--spec", self.write_spec({"title": "Synthetic"}))
        self.cli("remove-fact", result["record"]["id"], "--key", "missing", ok=False)

    def test_cli_add_and_fact_changes_persist(self):
        result = self.cli("create", "--spec", self.write_spec({"title": "Synthetic"}))
        entity = result["record"]["id"]
        self.cli(
            "add", entity, "--spec", self.write_spec({"user_text": "Later evidence"})
        )
        self.cli("set-fact", entity, "--key", "model", "--value", "TEST-123")
        self.assertEqual(
            self.cli("show", entity)["record"]["facts"][0]["value"], "TEST-123"
        )
        self.cli("remove-fact", entity, "--key", "model")
        self.cli("delete", entity)
        self.assertTrue(self.cli("show", entity)["record"]["deleted"])
        self.assertEqual(self.cli("search", "Synthetic")["results"], [])

    def test_invalid_spec_type_returns_failure(self):
        self.cli("create", "--spec", self.write_spec([]), ok=False)
        self.assertEqual(list(self.root.glob("records/*/metadata.json")), [])
