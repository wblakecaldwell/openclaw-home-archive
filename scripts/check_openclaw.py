#!/usr/bin/env python3
"""Read-only health and configuration check for OpenClaw Personal Archive integration."""

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

CONFIG_ROOT_KEY = "skills.entries.personal-archive.env.PERSONAL_ARCHIVE_ROOT"
ROUTING_MARKER = "PERSONAL ARCHIVE"


def get_openclaw_dir():
    if "OPENCLAW_HOME" in os.environ:
        return Path(os.environ["OPENCLAW_HOME"])
    return Path(os.path.expanduser("~/.openclaw"))


def config_get(key):
    """Read a configuration value from OpenClaw without mutating anything."""
    # First attempt with --json
    res = subprocess.run(
        ["openclaw", "config", "get", key, "--json"],
        capture_output=True,
        text=True,
        check=False,
    )
    if res.returncode != 0:
        # Retry without --json
        res = subprocess.run(
            ["openclaw", "config", "get", key],
            capture_output=True,
            text=True,
            check=False,
        )
        if res.returncode != 0:
            return None
    stdout = res.stdout.strip()
    if not stdout:
        return None
    try:
        return json.loads(stdout)
    except Exception:
        return stdout


def check(archive_root_arg, skill_dir, workspace_dir, summary_only=False):
    results = []

    # 1. OpenClaw CLI available
    cli_found = shutil.which("openclaw") is not None
    results.append(("OpenClaw CLI available on PATH", cli_found, "critical"))

    # 2. Skill installed and current
    skill_path = Path(skill_dir)
    skill_ok = (
        (skill_path / "SKILL.md").exists()
        and (skill_path / "scripts/personal_archive.py").exists()
        and os.access(skill_path / "scripts/personal_archive.py", os.X_OK)
    )
    results.append((f"Personal Archive skill installed ({skill_dir})", skill_ok, "critical"))

    # 3. Dedicated agent workspace provisioned and clean
    ws_path = Path(workspace_dir)
    ws_ok = (
        ws_path.exists()
        and (ws_path / "AGENTS.md").exists()
        and (ws_path / "IDENTITY.md").exists()
        and not (ws_path / "MEMORY.md").exists()
        and not (ws_path / "USER.md").exists()
    )
    results.append(
        (f"Dedicated agent workspace clean ({workspace_dir})", ws_ok, "critical")
    )

    # 4. Archive root configured and exists
    configured_root = config_get(CONFIG_ROOT_KEY)
    candidate_root = archive_root_arg or configured_root or os.environ.get("PERSONAL_ARCHIVE_ROOT")
    archive_dir_ok = False
    resolved_root = None
    if candidate_root and isinstance(candidate_root, str) and candidate_root.strip():
        p = Path(os.path.expanduser(candidate_root.strip()))
        if p.exists() and p.is_dir():
            archive_dir_ok = True
            resolved_root = str(p)

    results.append(
        (
            f"Archive directory exists and accessible ({resolved_root or candidate_root or 'unset'})",
            archive_dir_ok,
            "critical",
        )
    )

    # 5. Archive doctor passes
    doctor_ok = False
    if archive_dir_ok and resolved_root and skill_ok:
        script = skill_path / "scripts/personal_archive.py"
        env = dict(os.environ, PERSONAL_ARCHIVE_ROOT=resolved_root)
        doc_res = subprocess.run(
            [sys.executable, str(script), "doctor"],
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        if doc_res.returncode == 0:
            doctor_ok = True
    results.append(("Personal Archive doctor check passes", doctor_ok, "warn"))

    # 6. archivist agent registered in OpenClaw config
    agent = config_get("agents.entries.archivist")
    agent_registered = isinstance(agent, dict)
    results.append(
        ("archivist agent registered in OpenClaw configuration", agent_registered, "critical")
    )

    # 7. Agent workspace matches
    agent_ws = agent.get("workspace") if isinstance(agent, dict) else None
    ws_match = bool(
        agent_ws and (Path(os.path.expanduser(agent_ws)).resolve() == ws_path.resolve())
    )
    results.append(
        (f"archivist workspace points to dedicated directory", ws_match, "critical")
    )

    # 8. Agent has personal-archive skill
    skills = agent.get("skills") if isinstance(agent, dict) else None
    has_skill = isinstance(skills, list) and "personal-archive" in skills
    results.append(("archivist agent has 'personal-archive' skill", has_skill, "critical"))

    # 9. Agent memory restrictions
    mem_ok = False
    if isinstance(agent, dict):
        mem_cfg = agent.get("memory", {})
        search_cfg = mem_cfg.get("search", {}) if isinstance(mem_cfg, dict) else {}
        rem = search_cfg.get("rememberAcrossConversations")
        tool_denies = agent.get("tools", {}).get("deny", []) if isinstance(agent.get("tools"), dict) else []
        if rem is False and ("group:memory" in tool_denies):
            mem_ok = True
    results.append(
        (
            "archivist memory isolated (rememberAcrossConversations=false, group:memory denied)",
            mem_ok,
            "critical",
        )
    )

    # 10. Agent session tool restrictions
    tool_denies = agent.get("tools", {}).get("deny", []) if (isinstance(agent, dict) and isinstance(agent.get("tools"), dict)) else []
    session_tool_ok = "group:sessions" in tool_denies
    results.append(
        ("archivist session tools denied (group:sessions)", session_tool_ok, "critical")
    )

    # 11. Leaf worker configuration (cannot spawn subagents)
    subagents_cfg = agent.get("subagents", {}) if isinstance(agent, dict) else {}
    allow_subs = subagents_cfg.get("allowAgents")
    leaf_ok = (allow_subs == [])
    results.append(
        ("archivist configured as leaf agent (allowAgents=[])", leaf_ok, "critical")
    )

    # 12. Main agent does not directly execute personal-archive skill
    main_skills = config_get("agents.entries.main.skills")
    main_skill_clean = not (isinstance(main_skills, list) and "personal-archive" in main_skills)
    results.append(
        ("main agent does not directly execute 'personal-archive' skill", main_skill_clean, "critical")
    )

    # 13. Main agent delegation to archivist allowed (REQUIRED)
    main_allow = config_get("agents.entries.main.subagents.allowAgents")
    has_allow = isinstance(main_allow, list) and ("archivist" in main_allow)
    results.append(("main agent subagents.allowAgents includes 'archivist'", has_allow, "critical"))

    # 14. Main agent requireAgentId (recommended hardening)
    req_id = config_get("agents.entries.main.subagents.requireAgentId")
    results.append(
        ("main agent subagents.requireAgentId is true (recommended hardening)", req_id is True, "info")
    )

    # 15. Gateway session visibility is "tree" (recommended hardening)
    vis = config_get("tools.sessions.visibility")
    results.append(("Gateway tools.sessions.visibility is 'tree' (recommended hardening)", vis == "tree", "info"))

    # 16. Gateway agentToAgent messaging disabled (recommended hardening)
    a2a = config_get("tools.agentToAgent.enabled")
    results.append(("Gateway tools.agentToAgent.enabled is false (recommended hardening)", a2a is False, "info"))

    # 17. Active Memory plugin excludes archivist
    am_agents = config_get("plugins.entries.active-memory.config.agents")
    am_ok = True
    if isinstance(am_agents, list) and "archivist" in am_agents:
        am_ok = False
    results.append(("Active Memory plugin excludes 'archivist'", am_ok, "critical"))

    # 18. Main workspace AGENTS.md has routing directives
    openclaw_dir = get_openclaw_dir()
    main_agents_file = openclaw_dir / "workspace/AGENTS.md"
    routing_found = False
    if main_agents_file.exists():
        text = main_agents_file.read_text()
        if ROUTING_MARKER in text and "archivist" in text:
            routing_found = True
    results.append(
        ("Main workspace AGENTS.md contains Personal Archive routing directives", routing_found, "critical")
    )

    # Evaluation
    all_critical_passed = True
    failures = []
    for desc, passed, severity in results:
        if not passed:
            failures.append((desc, severity))
            if severity == "critical":
                all_critical_passed = False

    if summary_only:
        return 0 if all_critical_passed else 1

    print("=== OpenClaw Personal Archive Inspection ===")
    for desc, passed, severity in results:
        if passed:
            status = "[PASS]"
        elif severity == "info":
            status = "[INFO]"
        elif severity == "warn":
            status = "[WARN]"
        else:
            status = "[FAIL]"
        print(f"  {status} {desc}")
    print("==============================================")

    if all_critical_passed:
        print("All Personal Archive integration checks passed.")
        print("OpenClaw Personal Archive integration is complete and verified.")
        return 0
    else:
        print(f"\n{len(failures)} check(s) did not pass.", file=sys.stderr)
        print("To complete or repair your OpenClaw configuration, follow:", file=sys.stderr)
        print("    docs/OPENCLAW_SETUP.md", file=sys.stderr)
        print("Then rerun:", file=sys.stderr)
        print("    ./install.sh --check", file=sys.stderr)
        return 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive-root", help="Explicit archive root directory to check")
    parser.add_argument("--skill-directory", default=os.environ.get("SKILL_DIRECTORY"))
    parser.add_argument("--workspace-directory", default=os.environ.get("AGENT_WORKSPACE"))
    parser.add_argument("--summary", action="store_true", help="Quiet summary exit code only")
    args = parser.parse_args()

    skill_dir = args.skill_directory or str(get_openclaw_dir() / "workspace/skills/personal-archive")
    workspace_dir = args.workspace_directory or str(get_openclaw_dir() / "workspaces/archivist")

    return check(args.archive_root, skill_dir, workspace_dir, summary_only=args.summary)


if __name__ == "__main__":
    sys.exit(main())
