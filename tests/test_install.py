"""Exercise installation only inside disposable home directories."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

PROJECT = Path(__file__).resolve().parents[1]


class InstallTests(unittest.TestCase):
    def setUp(self):
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
        self.assertEqual(list(self.destination.parent.iterdir()), [self.destination])

    def test_install_leaves_openclaw_config_and_main_agents_untouched(self):
        # Prepare main AGENTS.md
        main_agents = self.user_home / ".openclaw/workspace/AGENTS.md"
        main_agents.parent.mkdir(parents=True, exist_ok=True)
        main_agents.write_text("# Main Agent Directives\nCustom content.\n")

        config_before = self.config.read_bytes()
        agents_before = main_agents.read_bytes()

        self.install()

        # install.sh MUST NOT modify openclaw configuration or main's AGENTS.md
        self.assertEqual(self.config.read_bytes(), config_before)
        self.assertEqual(main_agents.read_bytes(), agents_before)

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
                        "allow": ["read", "personal-archive/*"],
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
        data["mcp"] = {
            "servers": {
                "personal-archive": {
                    "command": "python3",
                    "args": ["scripts/mcp_server.py"],
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
                        "allow": ["read", "personal-archive/*"],
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
        data["mcp"] = {
            "servers": {
                "personal-archive": {
                    "command": "python3",
                    "args": ["scripts/mcp_server.py"],
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
        self.assertEqual(self.config.read_bytes(), config_before)

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


if __name__ == "__main__":
    unittest.main()
