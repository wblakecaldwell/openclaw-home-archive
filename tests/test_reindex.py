from http.server import HTTPServer, BaseHTTPRequestHandler
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import unittest

from tests.support import ArchiveTestCase

scripts_dir = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(scripts_dir))
import personal_archive  # noqa: E402
import reindex_archive  # noqa: E402


class ReindexTests(ArchiveTestCase):
    def setUp(self):
        super().setUp()
        old_root = os.environ.get("PERSONAL_ARCHIVE_ROOT")
        os.environ["PERSONAL_ARCHIVE_ROOT"] = str(self.root)
        if old_root is not None:
            self.addCleanup(lambda: os.environ.update({"PERSONAL_ARCHIVE_ROOT": old_root}))
        else:
            self.addCleanup(lambda: os.environ.pop("PERSONAL_ARCHIVE_ROOT", None))
        personal_archive.configure_root()
        personal_archive.init()

    def test_dry_run_leaves_archive_untouched(self):
        # Create a record with an image attachment
        card = self.source("card.jpg", b"\xff\xd8\xff\xe0TEST_JPEG")
        created = personal_archive.create({
            "title": "Test Card",
            "attachments": [{"path": str(card), "role": "business_card"}],
        })
        rid = created["id"]
        rec_dir = personal_archive.rdir(rid)
        meta_before = (rec_dir / "metadata.json").read_text()
        events_before = (rec_dir / "events.jsonl").read_text()

        # Run reindex in dry_run mode
        summary = reindex_archive.reindex_all(
            root=str(self.root),
            record_id=rid,
            dry_run=True,
            verbose=False,
        )

        self.assertTrue(summary["ok"])
        self.assertTrue(summary["dry_run"])
        # Disk content must be completely unmodified
        self.assertEqual((rec_dir / "metadata.json").read_text(), meta_before)
        self.assertEqual((rec_dir / "events.jsonl").read_text(), events_before)

    def test_reindex_enriches_record_with_mock_vision(self):
        # 1. Start mock vision server
        class MockVisionServer(BaseHTTPRequestHandler):
            def do_POST(self):
                body = self.rfile.read(int(self.headers.get("Content-Length", "0"))).decode("utf-8")
                _ = json.loads(body)
                response = {
                    "id": "chatcmpl-reindex-test",
                    "object": "chat.completion",
                    "choices": [
                        {
                            "index": 0,
                            "message": {
                                "role": "assistant",
                                "content": json.dumps({
                                    "title": "Example Decks - Joe Smith",
                                    "summary": "Business card for deck contractor Joe Smith.",
                                    "facts": [
                                        {"key": "contractor", "value": "Joe Smith"},
                                        {"key": "company", "value": "Example Decks"},
                                        {"key": "phone", "value": "(555) 123-4567"},
                                        {"key": "trade", "value": "Deck Builder"},
                                    ],
                                    "keywords": ["deck", "contractor", "carpentry", "outdoor"],
                                }),
                            },
                            "finish_reason": "stop",
                        }
                    ],
                }
                resp_bytes = json.dumps(response).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(resp_bytes)))
                self.end_headers()
                self.wfile.write(resp_bytes)

            def log_message(self, format, *args):
                pass

        server = HTTPServer(("127.0.0.1", 0), MockVisionServer)
        port = server.server_port
        t = threading.Thread(target=server.serve_forever, daemon=True)
        t.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)

        # 2. Point LMSTUDIO_URL to mock server
        old_url = os.environ.get("LMSTUDIO_URL")
        os.environ["LMSTUDIO_URL"] = f"http://127.0.0.1:{port}/v1"
        self.addCleanup(lambda: os.environ.update({"LMSTUDIO_URL": old_url}) if old_url else os.environ.pop("LMSTUDIO_URL", None))

        # 3. Create a record with image attachment and no facts
        card = self.source("contractor_card.jpg", b"\xff\xd8\xff\xe0TEST_JPEG")
        created = personal_archive.create({
            "title": "Joe's Card",
            "attachments": [{"path": str(card), "role": "business_card"}],
        })
        rid = created["id"]

        # 4. Run reindex
        summary = reindex_archive.reindex_all(
            root=str(self.root),
            record_id=rid,
            dry_run=False,
            verbose=False,
        )

        self.assertTrue(summary["ok"])
        self.assertEqual(summary["records_updated"], 1)
        self.assertEqual(summary["total_facts_added"], 4)
        self.assertEqual(summary["total_keywords_added"], 4)

        # 5. Verify persisted metadata.json
        rec = personal_archive.load(rid)
        facts = {f["key"]: f for f in rec["facts"]}
        self.assertIn("contractor", facts)
        self.assertEqual(facts["contractor"]["value"], "Joe Smith")
        self.assertEqual(facts["contractor"]["source"], "contractor_card.jpg")
        self.assertEqual(facts["contractor"]["confidence"], "high")

        self.assertIn("phone", facts)
        self.assertEqual(facts["phone"]["value"], "(555) 123-4567")

        self.assertIn("company", facts)
        self.assertEqual(facts["company"]["value"], "Example Decks")

        self.assertIn("deck", rec["keywords"])
        self.assertIn("carpentry", rec["keywords"])

        # 6. Verify event appended to events.jsonl
        events_file = personal_archive.rdir(rid) / "events.jsonl"
        events = [json.loads(line) for line in events_file.read_text().splitlines() if line.strip()]
        reindex_events = [e for e in events if e.get("type") == "reindex"]
        self.assertEqual(len(reindex_events), 1)
        self.assertEqual(len(reindex_events[0]["facts_added"]), 4)

        # 7. Verify record.md rendered with new facts
        md_text = (personal_archive.rdir(rid) / "record.md").read_text()
        self.assertIn("Joe Smith", md_text)
        self.assertIn("(555) 123-4567", md_text)

        # 8. Idempotency test: running reindex a second time should make 0 changes
        summary_2 = reindex_archive.reindex_all(
            root=str(self.root),
            record_id=rid,
            dry_run=False,
            verbose=False,
        )
        self.assertEqual(summary_2["records_updated"], 0)
        self.assertEqual(summary_2["records_unchanged"], 1)
        self.assertEqual(summary_2["total_facts_added"], 0)

    def test_user_facts_are_never_overwritten(self):
        # 1. Start mock vision server
        class MockVisionServer(BaseHTTPRequestHandler):
            def do_POST(self):
                response = {
                    "id": "chatcmpl-reindex-user-test",
                    "object": "chat.completion",
                    "choices": [
                        {
                            "index": 0,
                            "message": {
                                "role": "assistant",
                                "content": json.dumps({
                                    "facts": [
                                        {"key": "phone", "value": "555-VISION-WRONG"},
                                        {"key": "email", "value": "joe@example.com"},
                                    ],
                                    "keywords": ["deck"],
                                }),
                            },
                            "finish_reason": "stop",
                        }
                    ],
                }
                resp_bytes = json.dumps(response).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(resp_bytes)))
                self.end_headers()
                self.wfile.write(resp_bytes)

            def log_message(self, format, *args):
                pass

        server = HTTPServer(("127.0.0.1", 0), MockVisionServer)
        port = server.server_port
        t = threading.Thread(target=server.serve_forever, daemon=True)
        t.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)

        old_url = os.environ.get("LMSTUDIO_URL")
        os.environ["LMSTUDIO_URL"] = f"http://127.0.0.1:{port}/v1"
        self.addCleanup(lambda: os.environ.update({"LMSTUDIO_URL": old_url}) if old_url else os.environ.pop("LMSTUDIO_URL", None))

        # 2. Record has phone from user
        card = self.source("card2.jpg", b"\xff\xd8\xff\xe0TEST_JPEG")
        created = personal_archive.create({
            "title": "User Phone Record",
            "facts": [{"key": "phone", "value": "111-USER-CORRECT", "source": "user"}],
            "attachments": [{"path": str(card), "role": "business_card"}],
        })
        rid = created["id"]

        # 3. Run reindex with force=True
        summary = reindex_archive.reindex_all(
            root=str(self.root),
            record_id=rid,
            force=True,
            verbose=False,
        )

        rec = personal_archive.load(rid)
        active_facts = personal_archive.facts(rec)
        # User phone must be completely preserved!
        self.assertEqual(active_facts["phone"]["value"], "111-USER-CORRECT")
        self.assertEqual(active_facts["phone"]["source"], "user")
        # Brand new fact 'email' should have been added
        self.assertIn("email", active_facts)
        self.assertEqual(active_facts["email"]["value"], "joe@example.com")

    def test_force_supersedes_automated_facts_with_audit_trail(self):
        class MockVisionServer(BaseHTTPRequestHandler):
            def do_POST(self):
                response = {
                    "id": "chatcmpl-reindex-force-test",
                    "object": "chat.completion",
                    "choices": [
                        {
                            "index": 0,
                            "message": {
                                "role": "assistant",
                                "content": json.dumps({
                                    "facts": [
                                        {"key": "trade", "value": "Master Deck Builder"},
                                    ],
                                }),
                            },
                            "finish_reason": "stop",
                        }
                    ],
                }
                resp_bytes = json.dumps(response).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(resp_bytes)))
                self.end_headers()
                self.wfile.write(resp_bytes)

            def log_message(self, format, *args):
                pass

        server = HTTPServer(("127.0.0.1", 0), MockVisionServer)
        port = server.server_port
        t = threading.Thread(target=server.serve_forever, daemon=True)
        t.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)

        old_url = os.environ.get("LMSTUDIO_URL")
        os.environ["LMSTUDIO_URL"] = f"http://127.0.0.1:{port}/v1"
        self.addCleanup(lambda: os.environ.update({"LMSTUDIO_URL": old_url}) if old_url else os.environ.pop("LMSTUDIO_URL", None))

        # Record has automated fact with an old value
        card = self.source("card3.jpg", b"\xff\xd8\xff\xe0TEST_JPEG")
        created = personal_archive.create({
            "title": "Deck Record",
            "facts": [{"key": "trade", "value": "Carpenter", "source": "card3.jpg"}],
            "attachments": [{"path": str(card), "role": "business_card"}],
        })
        rid = created["id"]

        # Run reindex with force=True
        summary = reindex_archive.reindex_all(
            root=str(self.root),
            record_id=rid,
            force=True,
            verbose=False,
        )

        rec = personal_archive.load(rid)
        active_facts = personal_archive.facts(rec)
        self.assertEqual(active_facts["trade"]["value"], "Master Deck Builder")

        # Verify old fact is preserved in history as superseded
        all_facts = rec["facts"]
        self.assertEqual(len(all_facts), 2)
        old_fact = [f for f in all_facts if not f.get("active", True)][0]
        self.assertEqual(old_fact["value"], "Carpenter")
        self.assertEqual(old_fact["superseded_by_value"], "Master Deck Builder")

    def test_cli_subcommand_reindex(self):
        cli = scripts_dir / "personal_archive.py"
        res = subprocess.run(
            [sys.executable, str(cli), "reindex", "--dry-run"],
            capture_output=True,
            text=True,
            env=self.env,
        )
        self.assertEqual(res.returncode, 0, res.stderr)
        data = json.loads(res.stdout)
        self.assertTrue(data["ok"])
        self.assertTrue(data["dry_run"])


if __name__ == "__main__":
    unittest.main()
