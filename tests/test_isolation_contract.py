"""Tests for Personal Archive isolation contract, envelope schema, and template hygiene."""

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

PROJECT = Path(__file__).resolve().parents[1]
ID_PATTERN = re.compile(r"^ARCHIVE-\d{8}-\d{4}$")
ATT_ID_PATTERN = re.compile(r"^ARCHIVE-ATTACH-\d{8}-\d{4}$")


def validate_envelope(envelope):
    """Validate that a response envelope satisfies the Personal Archive contract."""
    if not isinstance(envelope, dict):
        raise ValueError("Envelope must be a JSON object")

    for required in ("ok", "source", "status", "relay_message"):
        if required not in envelope:
            raise ValueError(f"Missing required envelope field: {required}")

    if envelope["source"] != "personal-archive":
        raise ValueError(f"Invalid source: {envelope['source']}; expected 'personal-archive'")

    valid_statuses = {"found", "not_found", "mutated", "error"}
    if envelope["status"] not in valid_statuses:
        raise ValueError(f"Invalid status: {envelope['status']}; expected one of {valid_statuses}")

    if not isinstance(envelope["relay_message"], str) or not envelope["relay_message"].strip():
        raise ValueError("relay_message must be a non-empty string")

    # When status is found or mutated, record_id must be a valid deterministic identifier
    if envelope["status"] in ("found", "mutated"):
        record_id = envelope.get("record_id")
        if not record_id or not ID_PATTERN.match(record_id):
            raise ValueError(f"Invalid record_id format: {record_id}")

    # Validate evidence attachments if present
    for item in envelope.get("evidence", []):
        att_id = item.get("attachment_id")
        if att_id and not ATT_ID_PATTERN.match(att_id):
            raise ValueError(f"Invalid attachment_id format: {att_id}")

    return True


class IsolationContractTests(unittest.TestCase):
    def test_found_envelope_validates(self):
        envelope = {
            "ok": True,
            "source": "personal-archive",
            "operation": "search",
            "status": "found",
            "record_id": "ARCHIVE-20260920-0001",
            "relay_message": "The toaster is a Breville BTA820XL (Archive ID: ARCHIVE-20260920-0001).",
            "facts": {"brand": "Breville", "model": "BTA820XL"},
            "evidence": [
                {
                    "attachment_id": "ARCHIVE-ATTACH-20260920-0001",
                    "fact": "model",
                    "value": "BTA820XL",
                    "source": "receipt.pdf",
                }
            ],
        }
        self.assertTrue(validate_envelope(envelope))

    def test_not_found_envelope_validates(self):
        envelope = {
            "ok": True,
            "source": "personal-archive",
            "operation": "search",
            "status": "not_found",
            "record_id": None,
            "relay_message": "Personal Archive does not have a record of the lawnmower model.",
            "facts": {},
            "evidence": [],
        }
        self.assertTrue(validate_envelope(envelope))

    def test_mutated_envelope_validates(self):
        envelope = {
            "ok": True,
            "source": "personal-archive",
            "operation": "create",
            "status": "mutated",
            "record_id": "ARCHIVE-20260920-0002",
            "relay_message": "Created Personal Archive record for TestCo toaster (Archive ID: ARCHIVE-20260920-0002).",
            "facts": {"model": "TEST-123"},
            "evidence": [],
        }
        self.assertTrue(validate_envelope(envelope))

    def test_error_envelope_validates(self):
        envelope = {
            "ok": False,
            "source": "personal-archive",
            "operation": "create",
            "status": "error",
            "error": "FileNotFoundError: /tmp/attachment.jpg",
            "relay_message": "Failed to create archive record: the attachment file was not found.",
        }
        self.assertTrue(validate_envelope(envelope))

    def test_fabricated_id_is_rejected(self):
        for bad_id in (
            "ARCHIVE-2026-09-20-0001",  # extra dashes
            "ARCHIVE-toaster-1",        # descriptive slug
            "ARCHIVE-0001",             # missing date
            "12345",                    # raw number
            "PA-20260920-0001",         # obsolete prefix rejected
            "HA-20260920-0001",         # older prefix rejected
        ):
            with self.subTest(bad_id=bad_id):
                envelope = {
                    "ok": True,
                    "source": "personal-archive",
                    "status": "found",
                    "record_id": bad_id,
                    "relay_message": "Here is the record.",
                }
                with self.assertRaises(ValueError):
                    validate_envelope(envelope)

    def test_fabricated_attachment_id_is_rejected(self):
        for bad_aid in (
            "ARCHIVE-ATTACH-photo-1",
            "ARCHIVE-ATT-20260920-0001",
            "PAA-20260920-0001",
            "HAA-20260920-0001",
            "ARCHIVE-20260920-0001",
        ):
            with self.subTest(bad_aid=bad_aid):
                envelope = {
                    "ok": True,
                    "source": "personal-archive",
                    "status": "found",
                    "record_id": "ARCHIVE-20260920-0001",
                    "relay_message": "Record found.",
                    "evidence": [{"attachment_id": bad_aid, "fact": "model"}],
                }
                with self.assertRaises(ValueError):
                    validate_envelope(envelope)

    def test_invalid_status_or_source_is_rejected(self):
        with self.assertRaises(ValueError):
            validate_envelope({
                "ok": True,
                "source": "main",  # wrong source (expected 'personal-archive')
                "status": "found",
                "record_id": "ARCHIVE-20260920-0001",
                "relay_message": "Msg",
            })
        with self.assertRaises(ValueError):
            validate_envelope({
                "ok": True,
                "source": "home-archive",  # obsolete source rejected
                "status": "found",
                "record_id": "ARCHIVE-20260920-0001",
                "relay_message": "Msg",
            })
        with self.assertRaises(ValueError):
            validate_envelope({
                "ok": True,
                "source": "personal-archive",
                "status": "unknown_status",
                "record_id": "ARCHIVE-20260920-0001",
                "relay_message": "Msg",
            })

    def test_openclaw_templates_have_no_personal_paths(self):
        openclaw_dir = PROJECT / "openclaw"
        self.assertTrue(openclaw_dir.exists())
        for path in openclaw_dir.rglob("*"):
            if not path.is_file():
                continue
            content = path.read_text()
            # Assert no personal absolute paths exist in template files
            self.assertNotIn("/Users/", content, f"Personal absolute path found in {path}")
            self.assertNotIn("/home/", content, f"Personal absolute path found in {path}")
            self.assertNotIn("PRIVATE_KEY", content)
            self.assertNotIn("API_KEY", content)

    def test_openclaw_templates_contain_required_security_constraints(self):
        agent_cfg = (PROJECT / "openclaw/agent-archivist.json5").read_text()
        self.assertIn("group:sessions", agent_cfg)
        self.assertIn("group:memory", agent_cfg)
        self.assertIn("allowAgents", agent_cfg)
        # OpenClaw 2026.9.5 schema rejects maxSpawnDepth on agents.entries.<id>.subagents
        self.assertNotIn("maxSpawnDepth", agent_cfg)
        self.assertIn("rememberAcrossConversations", agent_cfg)

        main_patch = (PROJECT / "openclaw/agent-main-patch.json5").read_text()
        self.assertIn("requireAgentId", main_patch)
        self.assertIn("archivist", main_patch)

        gateway_cfg = (PROJECT / "openclaw/gateway-config.json5").read_text()
        self.assertIn('"tree"', gateway_cfg)
        self.assertIn("agentToAgent", gateway_cfg)

    def test_installer_provisions_agent_workspace(self):
        with tempfile.TemporaryDirectory(prefix="test-ws-provision-") as tmpdir:
            tmppath = Path(tmpdir)
            fake_home = tmppath / "home"
            fake_home.mkdir()
            fake_dest = fake_home / ".openclaw/workspace/skills/personal-archive"
            fake_agent_ws = fake_home / ".openclaw/workspaces/archivist"

            fake_bin = tmppath / "bin"
            fake_bin.mkdir()
            fake_openclaw = fake_bin / "openclaw"
            fake_openclaw.write_text(
                "#!"
                + sys.executable
                + "\n"
                + (PROJECT / "tests/fixtures/openclaw.py").read_text()
            )
            fake_openclaw.chmod(0o755)

            config = tmppath / "openclaw.json"
            config.write_text(
                json.dumps(
                    {
                        "skills": {
                            "entries": {
                                "personal-archive": {
                                    "env": {
                                        "PERSONAL_ARCHIVE_ROOT": str(tmppath / "archive"),
                                    }
                                }
                            }
                        }
                    }
                )
            )

            from http.server import HTTPServer, BaseHTTPRequestHandler
            import threading

            class MockLMHandler(BaseHTTPRequestHandler):
                def log_message(self, format, *args):
                    pass

                def do_GET(self):
                    if self.path == "/v1/models":
                        self.send_response(200)
                        self.send_header("Content-Type", "application/json")
                        self.end_headers()
                        self.wfile.write(json.dumps({"object": "list", "data": [{"id": "google/gemma-4-e4b"}]}).encode("utf-8"))
                    else:
                        self.send_response(404)
                        self.end_headers()

            mock_server = HTTPServer(("127.0.0.1", 0), MockLMHandler)
            mock_port = mock_server.server_port
            server_thread = threading.Thread(target=mock_server.serve_forever, daemon=True)
            server_thread.start()
            self.addCleanup(mock_server.server_close)
            self.addCleanup(mock_server.shutdown)

            env = dict(
                os.environ,
                HOME=str(fake_home),
                PATH=str(fake_bin) + os.pathsep + os.environ.get("PATH", ""),
                TEST_OPENCLAW_CONFIG=str(config),
                PERSONAL_ARCHIVE_ROOT=str(tmppath / "archive"),
                PERSONAL_ARCHIVIST_LMSTUDIO_URL=f"http://127.0.0.1:{mock_port}/v1",
                PERSONAL_ARCHIVIST_MODEL="google/gemma-4-e4b",
                PYTHONDONTWRITEBYTECODE="1",
            )

            result = subprocess.run(
                ["bash", str(PROJECT / "install.sh")],
                env=env,
                capture_output=True,
                text=True,
                timeout=15,
                stdin=subprocess.DEVNULL,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(fake_dest.exists())
            self.assertTrue((fake_dest / "SKILL.md").exists())

            # Verify dedicated agent workspace was provisioned
            self.assertTrue(fake_agent_ws.exists())
            self.assertTrue((fake_agent_ws / "AGENTS.md").exists())
            self.assertTrue((fake_agent_ws / "IDENTITY.md").exists())
            # Ensure no memory files were created in agent workspace
            self.assertFalse((fake_agent_ws / "MEMORY.md").exists())
            self.assertFalse((fake_agent_ws / "USER.md").exists())

    def test_readme_rollback_instructions_contain_no_wildcards(self):
        readme = (PROJECT / "openclaw/README.md").read_text()
        self.assertNotIn("bak-*", readme, "README.md contains ambiguous wildcard in rollback commands")

    def test_inaccessible_archive_root_fails_deterministically(self):
        with tempfile.TemporaryDirectory(prefix="test-blocked-root-") as tmpdir:
            blocked_root = Path(tmpdir) / "blocked"
            blocked_root.mkdir(0o000)
            try:
                result = subprocess.run(
                    [sys.executable, str(PROJECT / "scripts/personal_archive.py"), "search", "toaster"],
                    env=dict(os.environ, PERSONAL_ARCHIVE_ROOT=str(blocked_root), PYTHONDONTWRITEBYTECODE="1"),
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                self.assertEqual(result.returncode, 1)
                data = json.loads(result.stdout)
                self.assertFalse(data["ok"])
                self.assertEqual(data["error"], "PermissionError")
            finally:
                blocked_root.chmod(0o700)


if __name__ == "__main__":
    unittest.main()


