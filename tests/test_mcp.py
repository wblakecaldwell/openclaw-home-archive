from http.server import HTTPServer, BaseHTTPRequestHandler
import json
from pathlib import Path
import subprocess
import sys
import threading

from tests.support import ArchiveTestCase

MCP_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "mcp_server.py"
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import mcp_server  # noqa: E402


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
            "archive_inspect_image",
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

    def test_archive_inspect_image_missing_file_returns_error(self):
        self.rpc("initialize")
        resp = self.rpc(
            "tools/call",
            {"name": "archive_inspect_image", "arguments": {"path": "/nonexistent/image.jpg"}},
        )
        self.assertTrue(resp["result"]["isError"])
        content = json.loads(resp["result"]["content"][0]["text"])
        self.assertFalse(content["ok"])
        self.assertEqual(content["error"], "FileNotFoundError")

    def test_archive_inspect_image_calls_vision_endpoint(self):
        # 1. Setup mock LM Studio HTTP server
        received_requests = []

        class MockLMStudioHandler(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length).decode("utf-8"))
                received_requests.append(body)
                response = {
                    "id": "chatcmpl-mock",
                    "object": "chat.completion",
                    "choices": [
                        {
                            "index": 0,
                            "message": {
                                "role": "assistant",
                                "content": "Extracted Text: Joe Smith, Example Decks\nPhone: (555) 123-4567\nKeywords: deck, builder, Joe",
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
                pass  # quiet test logs

        server = HTTPServer(("127.0.0.1", 0), MockLMStudioHandler)
        port = server.server_port
        t = threading.Thread(target=server.serve_forever, daemon=True)
        t.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)

        # 2. Restart MCP process with LMSTUDIO_URL pointed to our mock server
        if self.proc.stdin:
            self.proc.stdin.close()
        if self.proc.stdout:
            self.proc.stdout.close()
        if self.proc.stderr:
            self.proc.stderr.close()
        self.proc.terminate()
        self.proc.wait()
        test_env = dict(self.env, LMSTUDIO_URL=f"http://127.0.0.1:{port}/v1")
        self.proc = subprocess.Popen(
            [sys.executable, str(MCP_SCRIPT)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=test_env,
            text=True,
            bufsize=1,
        )
        self.msg_id = 0
        self.rpc("initialize")

        # 3. Create a test image file
        card_file = self.source("business_card.jpg", b"\xff\xd8\xff\xe0FAKE_JPEG_BYTES")

        # 4. Call archive_inspect_image
        resp = self.rpc(
            "tools/call",
            {
                "name": "archive_inspect_image",
                "arguments": {
                    "path": str(card_file),
                    "context": "Extract contractor details",
                },
            },
        )
        self.assertFalse(resp["result"]["isError"])
        content = json.loads(resp["result"]["content"][0]["text"])
        self.assertTrue(content["ok"])
        self.assertEqual(content["operation"], "inspect_image")
        self.assertIn("Joe Smith", content["analysis"])

        # 5. Verify the payload sent to the mock vision server
        self.assertEqual(len(received_requests), 1)
        req_body = received_requests[0]
        self.assertIn("messages", req_body)
        user_msg = req_body["messages"][0]
        self.assertEqual(user_msg["role"], "user")
        content_items = user_msg["content"]
        # Must contain text prompt and image_url with data URI
        self.assertTrue(any(item.get("type") == "text" for item in content_items))
        image_items = [item for item in content_items if item.get("type") == "image_url"]
        self.assertEqual(len(image_items), 1)
        self.assertTrue(image_items[0]["image_url"]["url"].startswith("data:image/jpeg;base64,"))

    def test_parse_structured_extraction(self):
        # 1. Raw JSON
        raw_json = json.dumps({
            "title": "Breville Toaster",
            "summary": "4-slice toaster",
            "facts": [{"key": "model", "value": "BTA820XL"}],
            "keywords": ["toaster", "kitchen"],
        })
        res = mcp_server.parse_structured_extraction(raw_json)
        self.assertEqual(res["title"], "Breville Toaster")
        self.assertEqual(res["summary"], "4-slice toaster")
        self.assertEqual(res["facts"], [{"key": "model", "value": "BTA820XL"}])
        self.assertEqual(res["keywords"], ["toaster", "kitchen"])

        # 2. Markdown fenced code block
        fenced = (
            "Here is the extraction:\n```json\n"
            + json.dumps({
                "facts": {"brand": "Breville", "color": "silver"},
                "keywords": "kitchen, appliance",
            })
            + "\n```\nDone."
        )
        res_fenced = mcp_server.parse_structured_extraction(fenced)
        fact_keys = {f["key"]: f["value"] for f in res_fenced["facts"]}
        self.assertEqual(fact_keys["brand"], "Breville")
        self.assertEqual(fact_keys["color"], "silver")
        self.assertEqual(res_fenced["keywords"], ["kitchen", "appliance"])

        # 3. Fallback freeform text
        freeform = (
            "Title: Joe Smith Business Card\n"
            "Contractor: Joe Smith\n"
            "Phone: (555) 123-4567\n"
            "Trade: Deck Builder\n"
            "Keywords: deck, builder, carpentry\n"
        )
        res_freeform = mcp_server.parse_structured_extraction(freeform)
        self.assertEqual(res_freeform["title"], "Joe Smith Business Card")
        ff_facts = {f["key"]: f["value"] for f in res_freeform["facts"]}
        self.assertEqual(ff_facts["contractor"], "Joe Smith")
        self.assertEqual(ff_facts["phone"], "(555) 123-4567")
        self.assertEqual(ff_facts["trade"], "Deck Builder")
        self.assertEqual(res_freeform["keywords"], ["deck", "builder", "carpentry"])

    def test_archive_create_auto_enriches_from_vision(self):
        # 1. Start mock LM Studio server returning structured JSON
        class MockVisionServer(BaseHTTPRequestHandler):
            def do_POST(self):
                body = self.rfile.read(int(self.headers.get("Content-Length", "0"))).decode("utf-8")
                _ = json.loads(body)
                response = {
                    "id": "chatcmpl-mock-auto",
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

        # 2. Restart MCP process pointing to mock server
        if self.proc.stdin:
            self.proc.stdin.close()
        if self.proc.stdout:
            self.proc.stdout.close()
        if self.proc.stderr:
            self.proc.stderr.close()
        self.proc.terminate()
        self.proc.wait()
        test_env = dict(self.env, LMSTUDIO_URL=f"http://127.0.0.1:{port}/v1")
        self.proc = subprocess.Popen(
            [sys.executable, str(MCP_SCRIPT)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=test_env,
            text=True,
            bufsize=1,
        )
        self.msg_id = 0
        self.rpc("initialize")

        # 3. Create test card image
        card_file = self.source("contractor_card.jpg", b"\xff\xd8\xff\xe0CARD_JPEG_BYTES")

        # 4. Call archive_create passing the image attachment, with user text but no pre-extracted facts
        create_resp = self.rpc(
            "tools/call",
            {
                "name": "archive_create",
                "arguments": {
                    "title": "Joe's Business Card",
                    "user_text": "Here's Joe's card. He built our deck.",
                    "attachments": [
                        {
                            "path": str(card_file),
                            "role": "business_card",
                            "description": "Business card for deck contractor",
                        }
                    ],
                },
            },
        )
        self.assertFalse(create_resp["result"]["isError"])
        content = json.loads(create_resp["result"]["content"][0]["text"])
        self.assertTrue(content["ok"])
        self.assertEqual(content["operation"], "create")

        # Verify record has auto-extracted facts with provenance pointing to contractor_card.jpg
        rec = content["record"]
        facts = {f["key"]: f for f in rec["facts"]}
        self.assertIn("contractor", facts)
        self.assertEqual(facts["contractor"]["value"], "Joe Smith")
        self.assertEqual(facts["contractor"]["source"], "contractor_card.jpg")
        self.assertEqual(facts["contractor"]["confidence"], "high")

        self.assertIn("phone", facts)
        self.assertEqual(facts["phone"]["value"], "(555) 123-4567")

        self.assertIn("company", facts)
        self.assertEqual(facts["company"]["value"], "Example Decks")

        # Verify record has auto-extracted keywords
        keywords = rec["keywords"]
        self.assertIn("deck", keywords)
        self.assertIn("contractor", keywords)
        self.assertIn("carpentry", keywords)

        # 5. Test archive_add_evidence auto-enriches an existing record
        receipt_file = self.source("deck_receipt.jpg", b"\xff\xd8\xff\xe0RECEIPT_BYTES")
        add_resp = self.rpc(
            "tools/call",
            {
                "name": "archive_add_evidence",
                "arguments": {
                    "id": content["id"],
                    "user_text": "Found the receipt too.",
                    "attachments": [
                        {
                            "path": str(receipt_file),
                            "role": "receipt",
                        }
                    ],
                },
            },
        )
        self.assertFalse(add_resp["result"]["isError"])
        add_content = json.loads(add_resp["result"]["content"][0]["text"])
        self.assertTrue(add_content["ok"])
        self.assertEqual(len(add_content["attachments_added"]), 1)

    def test_query_vision_model_auth_and_model_override(self):
        received_requests = []

        class MockAuthVisionServer(BaseHTTPRequestHandler):
            def do_POST(self):
                auth_header = self.headers.get("Authorization")
                content_length = int(self.headers.get("Content-Length", "0"))
                body = self.rfile.read(content_length).decode("utf-8")
                req_json = json.loads(body)
                received_requests.append({"auth": auth_header, "body": req_json})

                if auth_header != "Bearer test-secret-token":
                    self.send_response(401)
                    self.send_header("Content-Type", "application/json")
                    err_payload = json.dumps({"error": "unauthorized"}).encode("utf-8")
                    self.send_header("Content-Length", str(len(err_payload)))
                    self.end_headers()
                    self.wfile.write(err_payload)
                    return

                resp = {
                    "choices": [
                        {"message": {"content": "{\"title\": \"Card\", \"facts\": [], \"keywords\": []}"}}
                    ]
                }
                resp_bytes = json.dumps(resp).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(resp_bytes)))
                self.end_headers()
                self.wfile.write(resp_bytes)

            def log_message(self, format, *args):
                pass

        server = HTTPServer(("127.0.0.1", 0), MockAuthVisionServer)
        port = server.server_port
        t = threading.Thread(target=server.serve_forever, daemon=True)
        t.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)

        import os
        old_pa_url = os.environ.get("PERSONAL_ARCHIVIST_LMSTUDIO_URL")
        old_url = os.environ.get("LMSTUDIO_URL")
        old_token = os.environ.get("PERSONAL_ARCHIVIST_LMSTUDIO_API_TOKEN")
        old_model = os.environ.get("PERSONAL_ARCHIVIST_MODEL")

        os.environ["PERSONAL_ARCHIVIST_LMSTUDIO_URL"] = f"http://127.0.0.1:{port}/v1"
        try:
            # 1. Without token, should fail with HTTP 401
            os.environ.pop("PERSONAL_ARCHIVIST_LMSTUDIO_API_TOKEN", None)
            os.environ.pop("LMSTUDIO_API_TOKEN", None)
            os.environ.pop("LM_API_TOKEN", None)
            with self.assertRaises(RuntimeError) as ctx:
                mcp_server.query_vision_model("data:image/jpeg;base64,AAAA", "test prompt")
            self.assertIn("LM Studio authentication failed (HTTP 401)", str(ctx.exception))

            # 2. With PERSONAL_ARCHIVIST_LMSTUDIO_API_TOKEN and PERSONAL_ARCHIVIST_MODEL
            os.environ["PERSONAL_ARCHIVIST_LMSTUDIO_API_TOKEN"] = "test-secret-token"
            os.environ["PERSONAL_ARCHIVIST_MODEL"] = "custom/my-vision-model"

            result = mcp_server.query_vision_model("data:image/jpeg;base64,AAAA", "test prompt")
            self.assertIn("title", result)

            self.assertEqual(len(received_requests), 2)
            self.assertEqual(received_requests[1]["auth"], "Bearer test-secret-token")
            self.assertEqual(received_requests[1]["body"]["model"], "custom/my-vision-model")
        finally:
            if old_pa_url is not None:
                os.environ["PERSONAL_ARCHIVIST_LMSTUDIO_URL"] = old_pa_url
            else:
                os.environ.pop("PERSONAL_ARCHIVIST_LMSTUDIO_URL", None)
            if old_url is not None:
                os.environ["LMSTUDIO_URL"] = old_url
            else:
                os.environ.pop("LMSTUDIO_URL", None)
            if old_token is not None:
                os.environ["PERSONAL_ARCHIVIST_LMSTUDIO_API_TOKEN"] = old_token
            else:
                os.environ.pop("PERSONAL_ARCHIVIST_LMSTUDIO_API_TOKEN", None)
            if old_model is not None:
                os.environ["PERSONAL_ARCHIVIST_MODEL"] = old_model
            else:
                os.environ.pop("PERSONAL_ARCHIVIST_MODEL", None)

