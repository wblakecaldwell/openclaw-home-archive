from http.server import HTTPServer, BaseHTTPRequestHandler
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest

PROJECT = Path(__file__).resolve().parents[1]


class MockLMStudioHandler(BaseHTTPRequestHandler):
    models = [{"id": "google/gemma-4-e4b", "object": "model"}]
    status_code = 200
    response_body = None
    required_token = None
    received_auth = None

    def log_message(self, format, *args):
        pass

    def do_GET(self):
        MockLMStudioHandler.received_auth = self.headers.get("Authorization")
        if MockLMStudioHandler.required_token:
            expected = f"Bearer {MockLMStudioHandler.required_token}"
            if MockLMStudioHandler.received_auth != expected:
                self.send_response(401)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"error": "Authentication required"}')
                return

        if self.path == "/v1/models":
            self.send_response(MockLMStudioHandler.status_code)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            if MockLMStudioHandler.response_body is not None:
                self.wfile.write(MockLMStudioHandler.response_body.encode("utf-8"))
            else:
                payload = {"object": "list", "data": MockLMStudioHandler.models}
                self.wfile.write(json.dumps(payload).encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()


class InstallTests(unittest.TestCase):
    def setUp(self):
        MockLMStudioHandler.models = [{"id": "google/gemma-4-e4b", "object": "model"}]
        MockLMStudioHandler.status_code = 200
        MockLMStudioHandler.response_body = None
        MockLMStudioHandler.required_token = None
        MockLMStudioHandler.received_auth = None

        self.mock_server = HTTPServer(("127.0.0.1", 0), MockLMStudioHandler)
        self.mock_port = self.mock_server.server_port
        self.server_thread = threading.Thread(target=self.mock_server.serve_forever, daemon=True)
        self.server_thread.start()
        self.addCleanup(self.mock_server.server_close)
        self.addCleanup(self.mock_server.shutdown)

        temporary = tempfile.TemporaryDirectory(prefix="personal-archive-install-test-")
        self.addCleanup(temporary.cleanup)
        self.workspace = Path(temporary.name)
        self.user_home = self.workspace / "test home"
        self.destination = self.user_home / ".openclaw/workspace/skills/personal-archive"
        self.agent_ws = self.user_home / ".openclaw/workspaces/archivist"
        self.source = self.workspace / "source checkout"
        (self.source / "scripts").mkdir(parents=True)
        (self.source / "openclaw").mkdir(parents=True, exist_ok=True)
        for name in (
            "install.sh",
            "SKILL.md",
            "README.md",
            "scripts/personal_archive.py",
            "scripts/mcp_server.py",
            "scripts/check_openclaw.py",
            "scripts/manage_directives.py",
            "scripts/reindex_archive.py",
            "openclaw/main-routing-instructions.md",
        ):
            shutil.copy2(PROJECT / name, self.source / name)
        if (PROJECT / "openclaw/workspace-archivist").exists():
            shutil.copytree(PROJECT / "openclaw/workspace-archivist", self.source / "openclaw/workspace-archivist")

        self.archive_root = self.workspace / "personal archive"
        self.archive_root.mkdir(parents=True, exist_ok=True)
        # HOME is supplied only to the child installer, never changed in this process.
        self.env = dict(
            os.environ,
            HOME=str(self.user_home),
            PERSONAL_ARCHIVE_ROOT=str(self.archive_root),
            PERSONAL_ARCHIVIST_LMSTUDIO_URL=f"http://127.0.0.1:{self.mock_port}/v1",
            PERSONAL_ARCHIVIST_MODEL="google/gemma-4-e4b",
            PYTHONDONTWRITEBYTECODE="1",
        )

        self.config = self.workspace / "openclaw.json"
        self.config.write_text(
            json.dumps(
                {
                    "skills": {
                        "entries": {
                            "personal-archive": {
                                "env": {
                                    "PERSONAL_ARCHIVE_ROOT": str(self.archive_root),
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

    def test_fresh_install_and_workspace_provisioning(self):
        result = self.install()
        # 1. Skill installed
        self.assertTrue(self.destination.exists())
        self.assertTrue((self.destination / "SKILL.md").exists())
        self.assertTrue((self.destination / "README.md").exists())
        self.assertTrue((self.destination / "scripts/personal_archive.py").exists())
        self.assertTrue(os.access(self.destination / "scripts/personal_archive.py", os.X_OK))
        self.assertTrue((self.destination / "scripts/mcp_server.py").exists())
        self.assertTrue(os.access(self.destination / "scripts/mcp_server.py", os.X_OK))
        self.assertTrue((self.destination / "scripts/manage_directives.py").exists())
        self.assertTrue(os.access(self.destination / "scripts/manage_directives.py", os.X_OK))
        self.assertTrue((self.destination / "scripts/reindex_archive.py").exists())
        self.assertTrue(os.access(self.destination / "scripts/reindex_archive.py", os.X_OK))

        # 2. Dedicated agent workspace provisioned
        self.assertTrue(self.agent_ws.exists())
        self.assertTrue((self.agent_ws / "AGENTS.md").exists())
        self.assertTrue((self.agent_ws / "IDENTITY.md").exists())
        self.assertFalse((self.agent_ws / "MEMORY.md").exists())
        self.assertFalse((self.agent_ws / "USER.md").exists())

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
        self.assertEqual(
            files,
            {
                "SKILL.md",
                "README.md",
                "scripts/personal_archive.py",
                "scripts/mcp_server.py",
                "scripts/manage_directives.py",
                "scripts/reindex_archive.py",
            },
        )
        for name in files:
            self.assertEqual(
                (self.destination / name).read_bytes(),
                (self.source / name).read_bytes(),
            )
        self.assertTrue(
            os.access(self.destination / "scripts/personal_archive.py", os.X_OK)
        )
        self.assertTrue(
            os.access(self.destination / "scripts/mcp_server.py", os.X_OK)
        )
        self.assertTrue(
            os.access(self.destination / "scripts/manage_directives.py", os.X_OK)
        )
        self.assertTrue(
            os.access(self.destination / "scripts/reindex_archive.py", os.X_OK)
        )
        self.assertEqual(list(self.destination.parent.iterdir()), [self.destination])

    def test_install_leaves_openclaw_config_and_main_agents_untouched(self):
        # Prepare main AGENTS.md
        main_agents = self.user_home / ".openclaw/workspace/AGENTS.md"
        main_agents.parent.mkdir(parents=True, exist_ok=True)
        main_agents.write_text("# Main Agent Directives\nCustom content.\n")

        config_before = json.loads(self.config.read_text())
        agents_before = main_agents.read_bytes()

        self.install()

        # install.sh MUST NOT modify unrelated openclaw configuration or main's AGENTS.md
        config_after = json.loads(self.config.read_text())
        self.assertEqual(config_after.get("unrelated"), config_before.get("unrelated"))
        self.assertEqual(main_agents.read_bytes(), agents_before)
        # But installer owns and configures mcp.servers.personal-archive
        self.assertIn("personal-archive", config_after.get("mcp", {}).get("servers", {}))
        mcp_cfg = config_after["mcp"]["servers"]["personal-archive"]
        self.assertEqual(mcp_cfg["command"], "python3")
        self.assertEqual(mcp_cfg["env"]["PERSONAL_ARCHIVIST_LMSTUDIO_URL"], f"http://127.0.0.1:{self.mock_port}/v1")
        self.assertEqual(mcp_cfg["env"]["PERSONAL_ARCHIVIST_MODEL"], "google/gemma-4-e4b")

    def test_existing_archive_is_preserved_never_deleted(self):
        archive = Path(self.env["PERSONAL_ARCHIVE_ROOT"])
        evidence = archive / "receipt.txt"
        evidence.write_bytes(b"Receipt evidence")

        self.install()

        self.assertTrue(evidence.exists())
        self.assertEqual(evidence.read_bytes(), b"Receipt evidence")

    def test_archive_initialization_when_missing(self):
        new_archive = self.workspace / "brand new archive"
        self.assertFalse(new_archive.exists())

        self.install(args=("--archive-root", str(new_archive)))

        self.assertTrue(new_archive.exists())
        self.assertTrue((new_archive / "records").exists())
        self.assertTrue((new_archive / "state/sequence.json").exists())

    def test_invalid_archive_location_rejected(self):
        for location in (
            "",
            "relative/path",
            "<archive-root>",
            str(self.destination / "data"),
        ):
            with self.subTest(location=location):
                self.install(args=("--archive-root", location), success=False)

    def test_check_is_strictly_read_only(self):
        main_agents = self.user_home / ".openclaw/workspace/AGENTS.md"
        main_agents.parent.mkdir(parents=True, exist_ok=True)
        main_agents.write_text("# Main Directives\n")

        config_before = self.config.read_bytes()
        agents_before = main_agents.read_bytes()

        # Run check
        self.install(args=("--check",), success=False)

        # Confirm 100% byte identical
        self.assertEqual(self.config.read_bytes(), config_before)
        self.assertEqual(main_agents.read_bytes(), agents_before)

    def test_check_reports_failure_on_missing_config_and_passes_when_configured(self):
        # 1. Initially, archivist agent is not registered and routing is missing
        res_fail = self.install(args=("--check",), success=False)
        self.assertIn("[FAIL]", res_fail.stdout)
        self.assertIn("docs/OPENCLAW_SETUP.md", res_fail.stderr)

        # 2. Install filesystem artifacts
        self.install()

        # 3. Simulate user completing configuration per docs/OPENCLAW_SETUP.md
        data = json.loads(self.config.read_text())
        data["agents"] = {
            "entries": {
                "main": {
                    "subagents": {
                        "requireAgentId": True,
                        "allowAgents": ["archivist"],
                    },
                    "skills": [],
                },
                "archivist": {
                    "name": "Archivist",
                    "workspace": "~/.openclaw/workspaces/archivist",
                    "skills": ["personal-archive"],
                    "tools": {
                        "allow": ["personal-archive/*"],
                        "deny": ["read", "exec", "write", "group:sessions", "group:memory"],
                    },
                    "memory": {
                        "search": {
                            "rememberAcrossConversations": False,
                        }
                    },
                    "subagents": {
                        "allowAgents": [],
                    },
                },
            }
        }
        data["mcp"] = {
            "servers": {
                "personal-archive": {
                    "command": "python3",
                    "args": ["scripts/mcp_server.py"],
                    "env": {
                        "PERSONAL_ARCHIVE_ROOT": str(self.archive_root),
                        "PERSONAL_ARCHIVIST_LMSTUDIO_URL": f"http://127.0.0.1:{self.mock_port}/v1",
                        "PERSONAL_ARCHIVIST_MODEL": "google/gemma-4-e4b",
                    },
                }
            }
        }
        data["tools"] = {
            "sessions": {"visibility": "tree"},
            "agentToAgent": {"enabled": False},
        }
        self.config.write_text(json.dumps(data))

        main_agents = self.user_home / ".openclaw/workspace/AGENTS.md"
        main_agents.parent.mkdir(parents=True, exist_ok=True)
        main_agents.write_text(
            "# Main Directives\n<!-- BEGIN OPENCLAW PERSONAL ARCHIVE MANAGED ROUTING DIRECTIVES -->\n"
            "archivist delegation directives\n<!-- END OPENCLAW PERSONAL ARCHIVE MANAGED ROUTING DIRECTIVES -->\n"
        )

        # Now check must pass
        res_pass = self.install(args=("--check",), success=True)
        self.assertIn("[PASS]", res_pass.stdout)
        self.assertIn("All Personal Archive integration checks passed", res_pass.stdout)

        # 4. Verify that omitting optional hardening (requireAgentId=False, default gateway settings) still passes check with [INFO]
        data["agents"]["entries"]["main"]["subagents"]["requireAgentId"] = False
        data["tools"] = {}
        self.config.write_text(json.dumps(data))
        res_info = self.install(args=("--check",), success=True)
        self.assertIn("[INFO]", res_info.stdout)
        self.assertIn("All Personal Archive integration checks passed", res_info.stdout)

    def test_check_allow_agents_states(self):
        # Setup passing installation baseline
        self.install()
        data = json.loads(self.config.read_text())
        data["agents"] = {
            "entries": {
                "main": {
                    "subagents": {
                        "requireAgentId": True,
                        "allowAgents": ["archivist"],
                    },
                    "skills": [],
                },
                "archivist": {
                    "name": "Archivist",
                    "workspace": "~/.openclaw/workspaces/archivist",
                    "skills": ["personal-archive"],
                    "tools": {
                        "allow": ["personal-archive/*"],
                        "deny": ["read", "exec", "write", "group:sessions", "group:memory"],
                    },
                    "memory": {
                        "search": {
                            "rememberAcrossConversations": False,
                        }
                    },
                    "subagents": {
                        "allowAgents": [],
                    },
                },
            }
        }
        data["mcp"] = {
            "servers": {
                "personal-archive": {
                    "command": "python3",
                    "args": ["scripts/mcp_server.py"],
                    "env": {
                        "PERSONAL_ARCHIVE_ROOT": str(self.archive_root),
                        "PERSONAL_ARCHIVIST_LMSTUDIO_URL": f"http://127.0.0.1:{self.mock_port}/v1",
                        "PERSONAL_ARCHIVIST_MODEL": "google/gemma-4-e4b",
                    },
                }
            }
        }
        self.config.write_text(json.dumps(data))
        main_agents = self.user_home / ".openclaw/workspace/AGENTS.md"
        main_agents.parent.mkdir(parents=True, exist_ok=True)
        main_agents.write_text(
            "# Main Directives\n<!-- BEGIN OPENCLAW PERSONAL ARCHIVE MANAGED ROUTING DIRECTIVES -->\n"
            "archivist delegation directives\n<!-- END OPENCLAW PERSONAL ARCHIVE MANAGED ROUTING DIRECTIVES -->\n"
        )

        # 1. Authored list with archivist alongside other agents passes and preserves them
        data["agents"]["entries"]["main"]["subagents"]["allowAgents"] = [
            "researcher",
            "coder",
            "archivist",
        ]
        self.config.write_text(json.dumps(data))
        res = self.install(args=("--check",), success=True)
        self.assertIn("[PASS] main agent subagents.allowAgents includes 'archivist'", res.stdout)
        # Verify check never modifies config
        current_config = json.loads(self.config.read_text())
        self.assertEqual(
            current_config["agents"]["entries"]["main"]["subagents"]["allowAgents"],
            ["researcher", "coder", "archivist"],
        )

        # 2. Authored list without archivist fails
        data["agents"]["entries"]["main"]["subagents"]["allowAgents"] = ["researcher", "coder"]
        self.config.write_text(json.dumps(data))
        res = self.install(args=("--check",), success=False)
        self.assertIn("[FAIL] main agent subagents.allowAgents includes 'archivist'", res.stdout)

        # 3. Empty authored list fails
        data["agents"]["entries"]["main"]["subagents"]["allowAgents"] = []
        self.config.write_text(json.dumps(data))
        res = self.install(args=("--check",), success=False)
        self.assertIn("[FAIL] main agent subagents.allowAgents includes 'archivist'", res.stdout)

        # 4. Unset allowAgents fails
        del data["agents"]["entries"]["main"]["subagents"]["allowAgents"]
        self.config.write_text(json.dumps(data))
        res = self.install(args=("--check",), success=False)
        self.assertIn("[FAIL] main agent subagents.allowAgents includes 'archivist'", res.stdout)

    def test_uninstall_removes_software_and_preserves_archive_and_config(self):
        # Setup archive with evidence
        archive = Path(self.env["PERSONAL_ARCHIVE_ROOT"])
        evidence = archive / "warranty.pdf"
        evidence.write_bytes(b"Warranty evidence")

        # Setup config and main AGENTS.md
        main_agents = self.user_home / ".openclaw/workspace/AGENTS.md"
        main_agents.parent.mkdir(parents=True, exist_ok=True)
        main_agents.write_text("# Main Agent Directives\nPreserved.\n")

        config_before = self.config.read_bytes()
        agents_before = main_agents.read_bytes()

        # Install
        self.install()
        self.assertTrue(self.destination.exists())
        self.assertTrue(self.agent_ws.exists())
        config_before_uninstall = self.config.read_bytes()

        # Uninstall
        res = self.install(args=("--uninstall",), success=True)
        self.assertIn("uninstalled successfully", res.stdout)
        self.assertIn("docs/OPENCLAW_SETUP.md#uninstall", res.stdout)

        # Filesystem cleanup: software artifacts removed
        self.assertFalse(self.destination.exists())
        self.assertFalse(self.agent_ws.exists())

        # CRITICAL INVARIANTS:
        # 1. Archive data must NOT be touched
        self.assertTrue(evidence.exists())
        self.assertEqual(evidence.read_bytes(), b"Warranty evidence")

        # 2. OpenClaw config must NOT be touched by uninstaller
        self.assertEqual(self.config.read_bytes(), config_before_uninstall)

        # 3. Main AGENTS.md must NOT be touched by default uninstaller
        self.assertEqual(main_agents.read_bytes(), agents_before)

    def test_install_and_uninstall_with_update_agents_context(self):
        main_agents = self.user_home / ".openclaw/workspace/AGENTS.md"
        main_agents.parent.mkdir(parents=True, exist_ok=True)
        main_agents.write_text("# Custom User Directives\nBe helpful and concise.\n")

        # 1. Install with --update-agents-context
        res = self.install(args=("--update-agents-context",), success=True)
        self.assertIn("Updating main agent routing directives", res.stdout)
        self.assertTrue(main_agents.exists())
        content = main_agents.read_text()
        self.assertIn("# Custom User Directives", content)
        self.assertIn("<!-- BEGIN OPENCLAW PERSONAL ARCHIVE MANAGED ROUTING DIRECTIVES -->", content)
        self.assertIn("<!-- END OPENCLAW PERSONAL ARCHIVE MANAGED ROUTING DIRECTIVES -->", content)
        self.assertIn("sessions_spawn", content)

        # 2. Re-running is idempotent
        res2 = self.install(args=("--update-agents-context",), success=True)
        self.assertEqual(main_agents.read_text(), content)

        # 3. Uninstall with --update-agents-context cleans directives while preserving custom content
        res_un = self.install(args=("--uninstall", "--update-agents-context"), success=True)
        self.assertIn("Removing routing directives", res_un.stdout)
        after_un = main_agents.read_text()
        self.assertEqual(after_un, "# Custom User Directives\nBe helpful and concise.\n")
        self.assertNotIn("<!-- BEGIN OPENCLAW PERSONAL ARCHIVE MANAGED ROUTING DIRECTIVES -->", after_un)

    def test_case_a_no_url_fails(self):
        """Case A: No URL in env, no URL in config => install fails."""
        self.env.pop("PERSONAL_ARCHIVIST_LMSTUDIO_URL", None)
        cfg = json.loads(self.config.read_text())
        cfg.get("mcp", {}).get("servers", {}).pop("personal-archive", None)
        self.config.write_text(json.dumps(cfg))

        res = self.install(success=False)
        self.assertIn("[FAIL] PERSONAL_ARCHIVIST_LMSTUDIO_URL is not configured", res.stderr + res.stdout)

    def test_case_b_url_and_model_in_env_writes_config(self):
        """Case B: URL + model in env, none in config => validates and writes config."""
        self.env["PERSONAL_ARCHIVIST_LMSTUDIO_URL"] = f"http://127.0.0.1:{self.mock_port}/v1"
        self.env["PERSONAL_ARCHIVIST_MODEL"] = "google/gemma-4-e4b"
        cfg = json.loads(self.config.read_text())
        cfg.get("mcp", {}).get("servers", {}).pop("personal-archive", None)
        self.config.write_text(json.dumps(cfg))

        self.install(success=True)

        updated_cfg = json.loads(self.config.read_text())
        mcp = updated_cfg.get("mcp", {}).get("servers", {}).get("personal-archive", {})
        self.assertEqual(mcp.get("command"), "python3")
        self.assertEqual(mcp.get("args"), [str(self.destination / "scripts/mcp_server.py")])
        self.assertEqual(mcp.get("env", {}).get("PERSONAL_ARCHIVIST_LMSTUDIO_URL"), f"http://127.0.0.1:{self.mock_port}/v1")
        self.assertEqual(mcp.get("env", {}).get("PERSONAL_ARCHIVIST_MODEL"), "google/gemma-4-e4b")
        self.assertEqual(mcp.get("env", {}).get("PERSONAL_ARCHIVE_ROOT"), str(self.archive_root))

    def test_case_c_no_env_vars_config_has_url_and_model_preserves_and_succeeds(self):
        """Case C: No env vars, config already has URL + model => preserves config and succeeds."""
        self.env.pop("PERSONAL_ARCHIVIST_LMSTUDIO_URL", None)
        self.env.pop("PERSONAL_ARCHIVIST_MODEL", None)

        cfg = json.loads(self.config.read_text())
        cfg.setdefault("mcp", {}).setdefault("servers", {})["personal-archive"] = {
            "command": "python3",
            "args": [str(self.destination / "scripts/mcp_server.py")],
            "env": {
                "PERSONAL_ARCHIVE_ROOT": str(self.archive_root),
                "PERSONAL_ARCHIVIST_LMSTUDIO_URL": f"http://127.0.0.1:{self.mock_port}/v1",
                "PERSONAL_ARCHIVIST_MODEL": "google/gemma-4-e4b",
                "PRESERVE_EXTRA": "custom-value",
            },
        }
        self.config.write_text(json.dumps(cfg))

        self.install(success=True)

        updated_cfg = json.loads(self.config.read_text())
        mcp_env = updated_cfg["mcp"]["servers"]["personal-archive"]["env"]
        self.assertEqual(mcp_env["PERSONAL_ARCHIVIST_LMSTUDIO_URL"], f"http://127.0.0.1:{self.mock_port}/v1")
        self.assertEqual(mcp_env["PERSONAL_ARCHIVIST_MODEL"], "google/gemma-4-e4b")
        self.assertEqual(mcp_env["PRESERVE_EXTRA"], "custom-value")

    def test_case_d_env_contains_new_valid_url_overwrites_config(self):
        """Case D: Env contains new valid URL => validates and overwrites existing configured URL."""
        new_server = HTTPServer(("127.0.0.1", 0), MockLMStudioHandler)
        new_port = new_server.server_port
        t = threading.Thread(target=new_server.serve_forever, daemon=True)
        t.start()
        self.addCleanup(new_server.server_close)
        self.addCleanup(new_server.shutdown)

        cfg = json.loads(self.config.read_text())
        cfg.setdefault("mcp", {}).setdefault("servers", {})["personal-archive"] = {
            "command": "python3",
            "args": [str(self.destination / "scripts/mcp_server.py")],
            "env": {
                "PERSONAL_ARCHIVE_ROOT": str(self.archive_root),
                "PERSONAL_ARCHIVIST_LMSTUDIO_URL": f"http://127.0.0.1:{self.mock_port}/v1",
                "PERSONAL_ARCHIVIST_MODEL": "google/gemma-4-e4b",
            },
        }
        self.config.write_text(json.dumps(cfg))

        self.env["PERSONAL_ARCHIVIST_LMSTUDIO_URL"] = f"http://127.0.0.1:{new_port}/v1"

        self.install(success=True)

        updated_cfg = json.loads(self.config.read_text())
        mcp_env = updated_cfg["mcp"]["servers"]["personal-archive"]["env"]
        self.assertEqual(mcp_env["PERSONAL_ARCHIVIST_LMSTUDIO_URL"], f"http://127.0.0.1:{new_port}/v1")

    def test_case_e_env_bad_url_config_valid_fails_and_config_unchanged(self):
        """Case E: Env contains bad/unresolvable URL while config contains valid URL
        => install fails and existing config remains unchanged."""
        valid_url = f"http://127.0.0.1:{self.mock_port}/v1"
        cfg = json.loads(self.config.read_text())
        cfg.setdefault("mcp", {}).setdefault("servers", {})["personal-archive"] = {
            "command": "python3",
            "args": [str(self.destination / "scripts/mcp_server.py")],
            "env": {
                "PERSONAL_ARCHIVE_ROOT": str(self.archive_root),
                "PERSONAL_ARCHIVIST_LMSTUDIO_URL": valid_url,
                "PERSONAL_ARCHIVIST_MODEL": "google/gemma-4-e4b",
            },
        }
        self.config.write_text(json.dumps(cfg))
        config_before = self.config.read_bytes()

        self.env["PERSONAL_ARCHIVIST_LMSTUDIO_URL"] = "http://bad-typo-host.invalid:1234/v1"

        res = self.install(success=False)
        self.assertIn("[FAIL] LM Studio hostname could not be resolved", res.stderr + res.stdout)
        self.assertEqual(self.config.read_bytes(), config_before)

    def test_case_f_configured_url_responds_but_model_missing_fails(self):
        """Case F: Configured URL responds but configured model missing => install/check fails clearly."""
        MockLMStudioHandler.models = [{"id": "some-other-model", "object": "model"}]
        self.env["PERSONAL_ARCHIVIST_LMSTUDIO_URL"] = f"http://127.0.0.1:{self.mock_port}/v1"
        self.env["PERSONAL_ARCHIVIST_MODEL"] = "google/gemma-4-e4b"

        # 1. install fails
        res_inst = self.install(success=False)
        self.assertIn("was not returned by /v1/models", res_inst.stderr + res_inst.stdout)

        # 2. check fails clearly
        cfg = json.loads(self.config.read_text())
        cfg.setdefault("mcp", {}).setdefault("servers", {})["personal-archive"] = {
            "command": "python3",
            "args": [str(self.destination / "scripts/mcp_server.py")],
            "env": {
                "PERSONAL_ARCHIVE_ROOT": str(self.archive_root),
                "PERSONAL_ARCHIVIST_LMSTUDIO_URL": f"http://127.0.0.1:{self.mock_port}/v1",
                "PERSONAL_ARCHIVIST_MODEL": "google/gemma-4-e4b",
            },
        }
        self.config.write_text(json.dumps(cfg))
        res_chk = self.install(args=("--check",), success=False)
        self.assertIn("[FAIL] Vision model google/gemma-4-e4b is available", res_chk.stdout)

    def test_case_g_check_performs_no_config_writes(self):
        """Case G: --check => performs no config writes."""
        cfg = json.loads(self.config.read_text())
        cfg["agents"] = {
            "entries": {
                "main": {
                    "subagents": {
                        "requireAgentId": True,
                        "allowAgents": ["archivist"],
                    },
                    "skills": [],
                },
                "archivist": {
                    "name": "Archivist",
                    "workspace": "~/.openclaw/workspaces/archivist",
                    "skills": ["personal-archive"],
                    "tools": {
                        "allow": ["personal-archive/*"],
                        "deny": ["read", "exec", "write", "group:sessions", "group:memory"],
                    },
                    "memory": {
                        "search": {
                            "rememberAcrossConversations": False,
                        }
                    },
                    "subagents": {
                        "allowAgents": [],
                    },
                },
            }
        }
        cfg["mcp"] = {
            "servers": {
                "personal-archive": {
                    "command": "python3",
                    "args": ["scripts/mcp_server.py"],
                    "env": {
                        "PERSONAL_ARCHIVE_ROOT": str(self.archive_root),
                        "PERSONAL_ARCHIVIST_LMSTUDIO_URL": f"http://127.0.0.1:{self.mock_port}/v1",
                        "PERSONAL_ARCHIVIST_MODEL": "google/gemma-4-e4b",
                    },
                }
            }
        }
        self.config.write_text(json.dumps(cfg))
        config_before = self.config.read_bytes()

        self.install(args=("--check",), success=False)

        self.assertEqual(self.config.read_bytes(), config_before)

    def test_lmstudio_token_authentication_flow(self):
        """Verify token is used during validation, persisted in MCP config, and used in --check."""
        MockLMStudioHandler.required_token = "secret-token-123"

        # 1. Without token, install fails with HTTP 401
        res_fail = self.install(success=False)
        self.assertIn("LM Studio authentication failed (HTTP 401)", res_fail.stderr + res_fail.stdout)
        self.assertIn("PERSONAL_ARCHIVIST_LMSTUDIO_API_TOKEN", res_fail.stderr + res_fail.stdout)

        # 2. With token in env, install succeeds and persists token
        self.env["PERSONAL_ARCHIVIST_LMSTUDIO_API_TOKEN"] = "secret-token-123"
        self.install(success=True)
        self.assertEqual(MockLMStudioHandler.received_auth, "Bearer secret-token-123")

        updated_cfg = json.loads(self.config.read_text())
        mcp_env = updated_cfg["mcp"]["servers"]["personal-archive"]["env"]
        self.assertEqual(mcp_env.get("PERSONAL_ARCHIVIST_LMSTUDIO_API_TOKEN"), "secret-token-123")

        # 3. Running --check without env token uses the persisted token from MCP config
        self.env.pop("PERSONAL_ARCHIVIST_LMSTUDIO_API_TOKEN", None)
        data = updated_cfg
        data["agents"] = {
            "entries": {
                "main": {
                    "subagents": {
                        "requireAgentId": True,
                        "allowAgents": ["archivist"],
                    },
                    "skills": [],
                },
                "archivist": {
                    "name": "Archivist",
                    "workspace": "~/.openclaw/workspaces/archivist",
                    "skills": ["personal-archive"],
                    "tools": {
                        "allow": ["personal-archive/*"],
                        "deny": ["read", "exec", "write", "group:sessions", "group:memory"],
                    },
                    "memory": {
                        "search": {
                            "rememberAcrossConversations": False,
                        }
                    },
                    "subagents": {
                        "allowAgents": [],
                    },
                },
            }
        }
        self.config.write_text(json.dumps(data))
        main_agents = self.user_home / ".openclaw/workspace/AGENTS.md"
        main_agents.parent.mkdir(parents=True, exist_ok=True)
        main_agents.write_text(
            "# Main Directives\n<!-- BEGIN OPENCLAW PERSONAL ARCHIVE MANAGED ROUTING DIRECTIVES -->\n"
            "archivist delegation directives\n<!-- END OPENCLAW PERSONAL ARCHIVE MANAGED ROUTING DIRECTIVES -->\n"
        )

        res_chk = self.install(args=("--check",), success=True)
        self.assertIn("[PASS] LM Studio API responds", res_chk.stdout)
        self.assertEqual(MockLMStudioHandler.received_auth, "Bearer secret-token-123")

    def test_check_resolves_unredacted_config_when_cli_redacts(self):
        """Verify check unredacts config from openclaw.json when CLI masks values."""
        self.install(success=True)

        data = json.loads(self.config.read_text())
        data["agents"] = {
            "entries": {
                "main": {
                    "subagents": {
                        "requireAgentId": True,
                        "allowAgents": ["archivist"],
                    },
                    "skills": [],
                },
                "archivist": {
                    "name": "Archivist",
                    "workspace": "~/.openclaw/workspaces/archivist",
                    "skills": ["personal-archive"],
                    "tools": {
                        "allow": ["personal-archive/*"],
                        "deny": ["read", "exec", "write", "group:sessions", "group:memory"],
                    },
                    "memory": {
                        "search": {
                            "rememberAcrossConversations": False,
                        }
                    },
                    "subagents": {
                        "allowAgents": [],
                    },
                },
            }
        }
        self.config.write_text(json.dumps(data))
        main_agents = self.user_home / ".openclaw/workspace/AGENTS.md"
        main_agents.parent.mkdir(parents=True, exist_ok=True)
        main_agents.write_text(
            "# Main Directives\n<!-- BEGIN OPENCLAW PERSONAL ARCHIVE MANAGED ROUTING DIRECTIVES -->\n"
            "archivist delegation directives\n<!-- END OPENCLAW PERSONAL ARCHIVE MANAGED ROUTING DIRECTIVES -->\n"
        )

        # Enable CLI redaction simulation
        self.env["TEST_OPENCLAW_REDACT_SECRETS"] = "1"
        res = self.install(args=("--check",), success=True)
        self.assertIn("[PASS] LM Studio API responds", res.stdout)
        self.assertIn("[PASS] Vision model google/gemma-4-e4b is available", res.stdout)
        self.assertNotIn("__OPENCLAW_REDACTED__", res.stdout)

    def test_installer_repairs_archivist_tool_policy(self):
        """Verify installer removes 'read' from allow and adds 'read' to deny."""
        # 1. Existing config allows 'read' and lacks 'read' in deny
        cfg = json.loads(self.config.read_text())
        cfg["agents"] = {
            "entries": {
                "archivist": {
                    "name": "Archivist",
                    "workspace": "~/.openclaw/workspaces/archivist",
                    "skills": ["personal-archive"],
                    "tools": {
                        "allow": ["read", "personal-archive/*"],
                        "deny": ["exec", "write", "group:sessions", "group:memory"],
                    },
                }
            }
        }
        self.config.write_text(json.dumps(cfg))

        # 2. Run installer
        self.install(success=True)

        # 3. Verify repaired configuration
        updated_cfg = json.loads(self.config.read_text())
        tools = updated_cfg["agents"]["entries"]["archivist"]["tools"]
        self.assertNotIn("read", tools["allow"])
        self.assertIn("personal-archive/*", tools["allow"])
        self.assertIn("read", tools["deny"])

    def test_checker_passes_when_archivist_filesystem_read_denied(self):
        """Verify check passes when personal-archive/* is allowed and read is denied."""
        self.install(success=True)
        data = json.loads(self.config.read_text())
        data["agents"] = {
            "entries": {
                "main": {
                    "subagents": {
                        "requireAgentId": True,
                        "allowAgents": ["archivist"],
                    },
                    "skills": [],
                },
                "archivist": {
                    "name": "Archivist",
                    "workspace": "~/.openclaw/workspaces/archivist",
                    "skills": ["personal-archive"],
                    "tools": {
                        "allow": ["personal-archive/*"],
                        "deny": ["read", "exec", "write", "group:sessions", "group:memory"],
                    },
                    "memory": {
                        "search": {
                            "rememberAcrossConversations": False,
                        }
                    },
                    "subagents": {
                        "allowAgents": [],
                    },
                },
            }
        }
        self.config.write_text(json.dumps(data))
        main_agents = self.user_home / ".openclaw/workspace/AGENTS.md"
        main_agents.parent.mkdir(parents=True, exist_ok=True)
        main_agents.write_text(
            "# Main Directives\n<!-- BEGIN OPENCLAW PERSONAL ARCHIVE MANAGED ROUTING DIRECTIVES -->\n"
            "archivist delegation directives\n<!-- END OPENCLAW PERSONAL ARCHIVE MANAGED ROUTING DIRECTIVES -->\n"
        )

        res = self.install(args=("--check",), success=True)
        self.assertIn("[PASS] archivist generic filesystem read denied", res.stdout)

    def test_checker_fails_critically_when_read_is_allowed(self):
        """Verify check fails critically when 'read' is present in tools.allow."""
        self.install(success=True)
        data = json.loads(self.config.read_text())
        data["agents"] = {
            "entries": {
                "main": {
                    "subagents": {
                        "requireAgentId": True,
                        "allowAgents": ["archivist"],
                    },
                    "skills": [],
                },
                "archivist": {
                    "name": "Archivist",
                    "workspace": "~/.openclaw/workspaces/archivist",
                    "skills": ["personal-archive"],
                    "tools": {
                        "allow": ["read", "personal-archive/*"],
                        "deny": ["read", "exec", "write", "group:sessions", "group:memory"],
                    },
                    "memory": {
                        "search": {
                            "rememberAcrossConversations": False,
                        }
                    },
                    "subagents": {
                        "allowAgents": [],
                    },
                },
            }
        }
        self.config.write_text(json.dumps(data))
        main_agents = self.user_home / ".openclaw/workspace/AGENTS.md"
        main_agents.parent.mkdir(parents=True, exist_ok=True)
        main_agents.write_text(
            "# Main Directives\n<!-- BEGIN OPENCLAW PERSONAL ARCHIVE MANAGED ROUTING DIRECTIVES -->\n"
            "archivist delegation directives\n<!-- END OPENCLAW PERSONAL ARCHIVE MANAGED ROUTING DIRECTIVES -->\n"
        )

        res = self.install(args=("--check",), success=False)
        self.assertIn("[FAIL] archivist generic filesystem read denied", res.stdout + res.stderr)

    def test_checker_fails_critically_when_read_is_not_denied(self):
        """Verify check fails critically when 'read' is absent from tools.deny."""
        self.install(success=True)
        data = json.loads(self.config.read_text())
        data["agents"] = {
            "entries": {
                "main": {
                    "subagents": {
                        "requireAgentId": True,
                        "allowAgents": ["archivist"],
                    },
                    "skills": [],
                },
                "archivist": {
                    "name": "Archivist",
                    "workspace": "~/.openclaw/workspaces/archivist",
                    "skills": ["personal-archive"],
                    "tools": {
                        "allow": ["personal-archive/*"],
                        "deny": ["exec", "write", "group:sessions", "group:memory"],
                    },
                    "memory": {
                        "search": {
                            "rememberAcrossConversations": False,
                        }
                    },
                    "subagents": {
                        "allowAgents": [],
                    },
                },
            }
        }
        self.config.write_text(json.dumps(data))
        main_agents = self.user_home / ".openclaw/workspace/AGENTS.md"
        main_agents.parent.mkdir(parents=True, exist_ok=True)
        main_agents.write_text(
            "# Main Directives\n<!-- BEGIN OPENCLAW PERSONAL ARCHIVE MANAGED ROUTING DIRECTIVES -->\n"
            "archivist delegation directives\n<!-- END OPENCLAW PERSONAL ARCHIVE MANAGED ROUTING DIRECTIVES -->\n"
        )

        res = self.install(args=("--check",), success=False)
        self.assertIn("[FAIL] archivist generic filesystem read denied", res.stdout + res.stderr)


if __name__ == "__main__":
    unittest.main()
