import hashlib
import json
from unittest.mock import patch

from tests.support import ArchiveTestCase


class ArchiveTests(ArchiveTestCase):
    def test_init_is_idempotent_and_preserves_sequence(self):
        self.assertEqual(self.archive.init()["root"], str(self.root))
        entity = self.archive.next_id("entity")
        before = self.snapshot()
        self.archive.init()
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(entity, "HA-20260920-0001")
        self.assertEqual(self.archive.next_id("entity"), "HA-20260920-0002")

    def test_id_sequences_are_separate_and_roll_over_daily(self):
        self.assertEqual(self.archive.next_id("entity"), "HA-20260920-0001")
        self.assertEqual(self.archive.next_id("attachment"), "HAA-20260920-0001")
        with patch.object(self.archive, "today", return_value="2026-09-21"):
            self.assertEqual(self.archive.next_id("entity"), "HA-20260921-0001")
            self.assertEqual(self.archive.next_id("attachment"), "HAA-20260921-0001")

    def test_create_persists_date_wording_and_views(self):
        record = self.create_record(
            event_date="2026-09-20",
            user_text="I bought this today.",
            facts=[{"key": "model", "value": "TEST-123", "source": "user"}],
        )
        entity = record["id"]
        self.assertEqual(self.archive.load(entity), record)
        self.assertEqual(record["event_date"], "2026-09-20")
        self.assertEqual(record["notes"][0]["text"], "I bought this today.")
        view = (self.archive.rdir(entity) / "record.md").read_text()
        self.assertIn(entity, view)
        self.assertIn("TEST-123", view)
        self.assertEqual(
            self.events(entity)[0]["spec"]["user_text"], "I bought this today."
        )

    def test_add_accumulates_evidence_and_append_only_history(self):
        record = self.create_record(user_text="First note", keywords=["kitchen"])
        event_path = self.archive.rdir(record["id"]) / "events.jsonl"
        before = event_path.read_bytes()
        source = self.source()
        self.archive.add(
            record["id"],
            {
                "user_text": "Later receipt",
                "keywords": ["kitchen", "receipt"],
                "attachments": [{"path": str(source)}],
            },
        )
        current = self.archive.load(record["id"])
        self.assertEqual(len(current["notes"]), 2)
        self.assertEqual(current["keywords"], ["kitchen", "receipt"])
        self.assertEqual(len(current["attachments"]), 1)
        self.assertTrue(event_path.read_bytes().startswith(before))
        self.assertEqual(
            [e["type"] for e in self.events(record["id"])], ["create", "add"]
        )

    def test_attachment_copy_hash_and_duplicate_detection(self):
        source = self.source()
        record = self.create_record(attachments=[{"path": str(source)}])
        attachment = record["attachments"][0]
        stored = self.archive.rdir(record["id"]) / attachment["stored_relpath"]
        self.assertEqual(stored.read_bytes(), source.read_bytes())
        self.assertEqual(
            attachment["sha256"], hashlib.sha256(source.read_bytes()).hexdigest()
        )
        source.write_bytes(b"Changed source after archival")
        self.assertEqual(stored.read_bytes(), b"Synthetic evidence")
        duplicate = self.source("duplicate.txt")
        result = self.archive.add(
            record["id"], {"attachments": [{"path": str(duplicate)}]}
        )
        self.assertEqual(result["attachments_added"], [])
        self.assertEqual(
            result["duplicates"][0]["existing_attachment"], attachment["id"]
        )
        self.assertEqual(len(self.archive.load(record["id"])["attachments"]), 1)

    def test_fact_update_and_removal_retain_history(self):
        record = self.create_record(facts=[{"key": "model", "value": "OLD"}])
        entity = record["id"]
        self.archive.setfact(entity, "model", "NEW", "user", "high")
        self.archive.rmfact(entity, "model")
        current = self.archive.load(entity)
        self.assertEqual(self.archive.facts(current), {})
        self.assertEqual([f["value"] for f in current["facts"]], ["OLD", "NEW"])
        self.assertEqual(
            [e["type"] for e in self.events(entity)],
            ["create", "set_fact", "remove_fact"],
        )
        before = self.snapshot()
        self.assertFalse(self.archive.rmfact(entity, "missing")["ok"])
        self.assertEqual(self.snapshot(), before)

    def test_removal_and_soft_delete_preserve_original(self):
        record = self.create_record(attachments=[{"path": str(self.source())}])
        attachment = record["attachments"][0]
        self.archive.rmatt(attachment["id"])
        self.archive.delete(record["id"])
        current, found = self.archive.find_att(attachment["id"])
        self.assertTrue(current["deleted"])
        self.assertFalse(found["active"])
        self.assertEqual(
            (self.archive.rdir(record["id"]) / found["stored_relpath"]).read_bytes(),
            b"Synthetic evidence",
        )
        self.assertEqual(self.archive.search("TestCo", 10), [])

    def test_search_ranks_title_matches_and_limits_results(self):
        summary = self.create_record(title="Appliance", summary="toaster")
        title = self.create_record(title="Toaster")
        results = self.archive.search("TOASTER", 1)
        self.assertEqual([r["id"] for r in results], [title["id"]])
        self.archive.delete(title["id"])
        self.assertEqual(self.archive.search("toaster", 10)[0]["id"], summary["id"])

    def test_merge_preserves_canonical_facts_and_source_evidence(self):
        canonical = self.create_record(facts=[{"key": "model", "value": "CANONICAL"}])
        duplicate = self.create_record(
            facts=[
                {"key": "model", "value": "OTHER"},
                {"key": "brand", "value": "TestCo"},
            ],
            attachments=[{"path": str(self.source())}],
            user_text="Source note",
        )
        result = self.archive.merge(canonical["id"], duplicate["id"])
        merged = self.archive.load(canonical["id"])
        source = self.archive.load(duplicate["id"])
        self.assertEqual(self.archive.facts(merged)["model"]["value"], "CANONICAL")
        self.assertEqual(self.archive.facts(merged)["brand"]["value"], "TestCo")
        self.assertEqual(self.archive.facts(source)["model"]["value"], "OTHER")
        self.assertTrue(source["deleted"])
        self.assertEqual(source["merged_into"], canonical["id"])
        self.assertEqual(
            result["attachments_moved"], [duplicate["attachments"][0]["id"]]
        )
        for record in (merged, source):
            path = (
                self.archive.rdir(record["id"])
                / record["attachments"][0]["stored_relpath"]
            )
            self.assertEqual(path.read_bytes(), b"Synthetic evidence")
        self.assertEqual(self.events(canonical["id"])[-1]["type"], "merge_in")
        self.assertEqual(self.events(duplicate["id"])[-1]["type"], "merged_into")

    def test_merge_with_self_is_rejected_without_changes(self):
        record = self.create_record()
        before = self.snapshot()
        with self.assertRaises(ValueError):
            self.archive.merge(record["id"], record["id"])
        self.assertEqual(self.snapshot(), before)

    def test_atomic_json_preserves_old_file_on_replace_failure(self):
        path = self.root / "state" / "sample.json"
        self.archive.atomic_json(path, {"value": "old"})
        with patch.object(
            self.archive.os, "replace", side_effect=OSError("simulated failure")
        ):
            with self.assertRaises(OSError):
                self.archive.atomic_json(path, {"value": "new"})
        self.assertEqual(json.loads(path.read_text()), {"value": "old"})
        self.assertEqual(list(path.parent.iterdir()), [path])

    def test_doctor_detects_corrupt_and_missing_evidence(self):
        record = self.create_record(attachments=[{"path": str(self.source())}])
        path = (
            self.archive.rdir(record["id"]) / record["attachments"][0]["stored_relpath"]
        )
        with patch.object(
            self.archive, "photos_ok", return_value=(False, "test isolation")
        ):
            self.assertTrue(self.archive.doctor()["ok"])
            path.write_bytes(b"Corrupted")
            result = self.archive.doctor()
            self.assertFalse(result["ok"])
            self.assertTrue(any("hash mismatch" in p for p in result["problems"]))
            path.unlink()
            result = self.archive.doctor()
            self.assertFalse(result["ok"])
            self.assertTrue(any("missing attachment" in p for p in result["problems"]))
