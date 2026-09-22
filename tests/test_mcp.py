"""Tests for the Model Context Protocol (MCP) server stdio interface."""

import json
from pathlib import Path
import subprocess
import sys

from tests.support import ArchiveTestCase

MCP_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "mcp_server.py"


class MCPTests(ArchiveTestCase):
    def setUp(self):
        super().setUp()
        self.proc = subprocess.Popen(
            [sys.executable, str(MCP_SCRIPT)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=self.env,
            text=True,
            bufsize=1,
        )
        self.msg_id = 0

    def tearDown(self):
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        if self.proc.stdin:
            self.proc.stdin.close()
        if self.proc.stdout:
            self.proc.stdout.close()
        if self.proc.stderr:
            self.proc.stderr.close()
        super().tearDown()

    def rpc(self, method, params=None):
        self.msg_id += 1
        req_id = self.msg_id
        payload = {"jsonrpc": "2.0", "id": req_id, "method": method}
        if params is not None:
            payload["params"] = params
        self.proc.stdin.write(json.dumps(payload) + "\n")
        self.proc.stdin.flush()
        line = self.proc.stdout.readline()
        self.assertTrue(line, "Server closed stdout unexpectedly")
        resp = json.loads(line)
        self.assertEqual(resp.get("id"), req_id)
        return resp

    def notify(self, method, params=None):
        payload = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            payload["params"] = params
        self.proc.stdin.write(json.dumps(payload) + "\n")
        self.proc.stdin.flush()

    def test_handshake_and_ping(self):
        # 1. Initialize
        init_resp = self.rpc(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "test-client", "version": "1.0"},
            },
        )
        self.assertIn("result", init_resp)
        self.assertEqual(init_resp["result"]["protocolVersion"], "2024-11-05")
        self.assertEqual(init_resp["result"]["serverInfo"]["name"], "personal-archive")
        self.assertIn("tools", init_resp["result"]["capabilities"])

        # 2. Initialized notification
        self.notify("notifications/initialized")

        # 3. Ping
        ping_resp = self.rpc("ping")
        self.assertEqual(ping_resp["result"], {})

    def test_tools_list_exposes_all_archive_tools(self):
        self.rpc("initialize")
        resp = self.rpc("tools/list")
        self.assertIn("result", resp)
        tools = resp["result"]["tools"]
        tool_names = {t["name"] for t in tools}
        expected = {
            "archive_create",
            "archive_search",
            "archive_show",
            "archive_add_evidence",
            "archive_set_fact",
            "archive_get_attachment",
            "archive_delete",
            "archive_doctor",
        }
        self.assertEqual(tool_names, expected)

        # Check that schemas specify required arguments
        tools_by_name = {t["name"]: t for t in tools}
        self.assertIn("title", tools_by_name["archive_create"]["inputSchema"]["required"])
        self.assertIn("query", tools_by_name["archive_search"]["inputSchema"]["required"])
        self.assertIn("id", tools_by_name["archive_show"]["inputSchema"]["required"])

    def test_tool_calls_end_to_end(self):
        self.rpc("initialize")

        # 1. archive_create
        evidence = self.source("toaster.jpg", b"fake toaster photo")
        create_resp = self.rpc(
            "tools/call",
            {
                "name": "archive_create",
                "arguments": {
                    "title": "Breville Toaster",
                    "user_text": "I bought this toaster today.",
                    "event_date": "2026-09-20",
                    "facts": [
                        {"key": "brand", "value": "Breville", "source": "user", "confidence": "high"},
                        {"key": "model", "value": "BTA820XL", "source": "toaster.jpg", "confidence": "high"},
                    ],
                    "attachments": [
                        {
                            "path": str(evidence),
                            "role": "photo",
                            "description": "Front face of toaster",
                        }
                    ],
                },
            },
        )
        self.assertFalse(create_resp["result"]["isError"])
        content = json.loads(create_resp["result"]["content"][0]["text"])
        self.assertTrue(content["ok"])
        record_id = content["id"]
        self.assertTrue(record_id.startswith("ARCHIVE-"))
        self.assertEqual(content["title"], "Breville Toaster")
        self.assertEqual(len(content["attachments_added"]), 1)
        attach_id = content["attachments_added"][0]["id"]
        self.assertTrue(attach_id.startswith("ARCHIVE-ATTACH-"))

        # 2. archive_show
        show_resp = self.rpc("tools/call", {"name": "archive_show", "arguments": {"id": record_id}})
        self.assertFalse(show_resp["result"]["isError"])
        show_content = json.loads(show_resp["result"]["content"][0]["text"])
        self.assertTrue(show_content["ok"])
        self.assertEqual(show_content["record"]["title"], "Breville Toaster")
        self.assertEqual(show_content["record"]["event_date"], "2026-09-20")

        # 3. archive_search
        search_resp = self.rpc("tools/call", {"name": "archive_search", "arguments": {"query": "Breville"}})
        self.assertFalse(search_resp["result"]["isError"])
        search_content = json.loads(search_resp["result"]["content"][0]["text"])
        self.assertTrue(search_content["ok"])
        self.assertEqual(len(search_content["results"]), 1)
        self.assertEqual(search_content["results"][0]["id"], record_id)

        # 4. archive_set_fact
        set_fact_resp = self.rpc(
            "tools/call",
            {
                "name": "archive_set_fact",
                "arguments": {
                    "id": record_id,
                    "key": "serial_number",
                    "value": "SN-999888",
                    "source": "plate_photo",
                    "confidence": "high",
                },
            },
        )
        self.assertFalse(set_fact_resp["result"]["isError"])
        set_fact_content = json.loads(set_fact_resp["result"]["content"][0]["text"])
        self.assertTrue(set_fact_content["ok"])

        # 5. archive_add_evidence
        add_resp = self.rpc(
            "tools/call",
            {
                "name": "archive_add_evidence",
                "arguments": {
                    "id": record_id,
                    "user_text": "Added extra warranty info.",
                    "facts": {"warranty_years": "2"},
                },
            },
        )
        self.assertFalse(add_resp["result"]["isError"])
        add_content = json.loads(add_resp["result"]["content"][0]["text"])
        self.assertTrue(add_content["ok"])

        # 6. archive_get_attachment
        get_att_resp = self.rpc(
            "tools/call",
            {
                "name": "archive_get_attachment",
                "arguments": {"id": attach_id},
            },
        )
        self.assertFalse(get_att_resp["result"]["isError"])
        get_att_content = json.loads(get_att_resp["result"]["content"][0]["text"])
        self.assertTrue(get_att_content["ok"])
        self.assertEqual(get_att_content["record"], record_id)
        self.assertTrue(Path(get_att_content["path"]).is_file())

        # 7. archive_doctor
        doc_resp = self.rpc("tools/call", {"name": "archive_doctor", "arguments": {}})
        self.assertFalse(doc_resp["result"]["isError"])
        doc_content = json.loads(doc_resp["result"]["content"][0]["text"])
        self.assertIn("root", doc_content)
        self.assertEqual(doc_content["records"], 1)

        # 8. archive_delete
        del_resp = self.rpc("tools/call", {"name": "archive_delete", "arguments": {"id": record_id}})
        self.assertFalse(del_resp["result"]["isError"])
        del_content = json.loads(del_resp["result"]["content"][0]["text"])
        self.assertTrue(del_content["ok"])
        self.assertTrue(del_content.get("soft_deleted") or del_content.get("deleted"))

        # Search should no longer return deleted record
        search_after = self.rpc("tools/call", {"name": "archive_search", "arguments": {"query": "Breville"}})
        self.assertEqual(json.loads(search_after["result"]["content"][0]["text"])["results"], [])

    def test_tool_call_error_handling(self):
        self.rpc("initialize")

        # Unknown method returns JSON-RPC protocol error
        unknown_method = self.rpc("nonexistent_method")
        self.assertIn("error", unknown_method)
        self.assertEqual(unknown_method["error"]["code"], -32601)

        # Unknown tool returns isError: True
        unknown_tool = self.rpc("tools/call", {"name": "fake_tool", "arguments": {}})
        self.assertTrue(unknown_tool["result"]["isError"])
        content = json.loads(unknown_tool["result"]["content"][0]["text"])
        self.assertFalse(content["ok"])
        self.assertEqual(content["error"], "ValueError")

        # Tool execution error (e.g. non-existent entity) returns isError: True with detail
        bad_id_resp = self.rpc(
            "tools/call",
            {"name": "archive_show", "arguments": {"id": "ARCHIVE-20260920-9999"}},
        )
        self.assertTrue(bad_id_resp["result"]["isError"])
        bad_id_content = json.loads(bad_id_resp["result"]["content"][0]["text"])
        self.assertFalse(bad_id_content["ok"])
        self.assertIn("error", bad_id_content)
