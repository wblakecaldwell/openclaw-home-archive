#!/usr/bin/env python3
"""Read-only health and configuration check for OpenClaw Personal Archive integration."""

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

CONFIG_ROOT_KEY = "skills.entries.personal-archive.env.PERSONAL_ARCHIVE_ROOT"
ROUTING_MARKER = "PERSONAL ARCHIVE"


def get_openclaw_dir():
    if "OPENCLAW_HOME" in os.environ:
        return Path(os.environ["OPENCLAW_HOME"])
    return Path(os.path.expanduser("~/.openclaw"))


def read_openclaw_config_file():
    """Read the raw OpenClaw config file directly to avoid CLI redaction (__OPENCLAW_REDACTED__)."""
    candidates = []
    if "TEST_OPENCLAW_CONFIG" in os.environ:
        candidates.append(Path(os.environ["TEST_OPENCLAW_CONFIG"]))
    if "OPENCLAW_CONFIG_PATH" in os.environ:
        candidates.append(Path(os.environ["OPENCLAW_CONFIG_PATH"]))

    openclaw_dir = get_openclaw_dir()
    candidates.append(openclaw_dir / "openclaw.json")
    candidates.append(openclaw_dir / "openclaw.json5")
    candidates.append(Path.home() / ".openclaw/openclaw.json")
    candidates.append(Path.home() / ".openclaw/openclaw.json5")

    for path in candidates:
        if path and path.is_file():
            try:
                text = path.read_text(encoding="utf-8")
                try:
                    return json.loads(text)
                except Exception:
                    pass
                clean = re.sub(r"//.*", "", text)
                clean = re.sub(r"/\*.*?\*/", "", clean, flags=re.DOTALL)
                clean = re.sub(r",\s*([}\]])", r"\1", clean)
                clean = re.sub(
                    r"([{,]\s*)([a-zA-Z_][a-zA-Z0-9_-]*)\s*:",
                    lambda m: m.group(1) + '"' + m.group(2) + '":',
                    clean,
                )
                return json.loads(clean)
            except Exception:
                continue
    return None


def config_get_from_file(key):
    """Retrieve key from the unredacted openclaw.json / openclaw.json5 file on disk."""
    cfg = read_openclaw_config_file()
    if not isinstance(cfg, dict):
        return None
    val = cfg
    for part in key.split("."):
        if not isinstance(val, dict) or part not in val:
            return None
        val = val[part]
    return val


def _has_redaction(obj):
    if isinstance(obj, str):
        return "__OPENCLAW_REDACTED__" in obj
    if isinstance(obj, dict):
        return any(_has_redaction(v) for v in obj.values())
    if isinstance(obj, list):
        return any(_has_redaction(item) for item in obj)
    return False


def _unredact(res_obj, file_obj):
    if res_obj is None or _has_redaction(res_obj):
        return file_obj if file_obj is not None else res_obj
    if isinstance(res_obj, dict) and isinstance(file_obj, dict):
        merged = dict(res_obj)
        for k, v in file_obj.items():
            if k not in merged or _has_redaction(merged[k]):
                merged[k] = v
            elif isinstance(merged[k], dict) and isinstance(v, dict):
                merged[k] = _unredact(merged[k], v)
        return merged
    return res_obj


def config_get(key):
    """Read a configuration value from OpenClaw without mutating anything.

    If the value returned by CLI is redacted (__OPENCLAW_REDACTED__) or CLI is missing,
    falls back to reading the raw config file directly from disk.
    """
    result = None
    try:
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
            if res.returncode == 0:
                stdout = res.stdout.strip()
                if stdout and "Config path is valid but unset" not in stdout:
                    try:
                        result = json.loads(stdout)
                    except Exception:
                        result = stdout
        else:
            stdout = res.stdout.strip()
            if stdout and "Config path is valid but unset" not in stdout:
                try:
                    result = json.loads(stdout)
                except Exception:
                    result = stdout
    except (FileNotFoundError, OSError):
        result = None

    if result is None or _has_redaction(result):
        file_val = config_get_from_file(key)
        result = _unredact(result, file_val)

    return result


def config_set(key, value):
    """Write a configuration value to OpenClaw."""
    val_str = json.dumps(value)
    try:
        res = subprocess.run(
            ["openclaw", "config", "set", key, val_str, "--strict-json"],
            capture_output=True,
            text=True,
            check=False,
        )
        if res.returncode != 0:
            res = subprocess.run(
                ["openclaw", "config", "set", key, val_str],
                capture_output=True,
                text=True,
                check=False,
            )
        return res.returncode == 0
    except (FileNotFoundError, OSError):
        return False


class LMStudioValidationResult:
    def __init__(
        self,
        ok=False,
        valid_url=False,
        host_resolves=False,
        api_responds=False,
        model_available=False,
        error_message=None,
        models=None,
        endpoint=None,
        hostname=None,
    ):
        self.ok = ok
        self.valid_url = valid_url
        self.host_resolves = host_resolves
        self.api_responds = api_responds
        self.model_available = model_available
        self.error_message = error_message
        self.models = models or []
        self.endpoint = endpoint
        self.hostname = hostname


def get_lmstudio_token(proc_env=None, cfg_env=None):
    """Resolve LM Studio API token from environment or config."""
    pe = os.environ if proc_env is None else proc_env
    ce = cfg_env
    if ce is None:
        mcp_cfg = config_get("mcp.servers.personal-archive")
        if isinstance(mcp_cfg, dict) and isinstance(mcp_cfg.get("env"), dict):
            ce = mcp_cfg["env"]
        else:
            ce = {}
    return (
        pe.get("PERSONAL_ARCHIVIST_LMSTUDIO_API_TOKEN")
        or pe.get("LMSTUDIO_API_TOKEN")
        or pe.get("LM_API_TOKEN")
        or pe.get("LMSTUDIO_API_KEY")
        or ce.get("PERSONAL_ARCHIVIST_LMSTUDIO_API_TOKEN")
        or ce.get("LMSTUDIO_API_TOKEN")
        or ce.get("LM_API_TOKEN")
        or ce.get("LMSTUDIO_API_KEY")
    )


def validate_lmstudio(url, model=None, token=None, timeout=5.0):
    """Validate LM Studio URL and model availability via /models.

    Checks:
    - URL scheme (http/https) and hostname presence
    - Hostname DNS resolution
    - HTTP GET <url>/models connectivity and 200 response (with Authorization bearer token if configured)
    - Valid OpenAI-compatible JSON with top-level 'data' array
    - If model is provided, presence of model id in returned models
    """
    if not url or not isinstance(url, str) or not url.strip():
        return LMStudioValidationResult(
            ok=False,
            error_message="[FAIL] PERSONAL_ARCHIVIST_LMSTUDIO_URL is not configured.",
        )

    clean_url = url.strip()
    try:
        parsed = urllib.parse.urlparse(clean_url)
    except Exception:
        return LMStudioValidationResult(
            ok=False,
            error_message=f"[FAIL] Malformed LM Studio URL: '{clean_url}'.",
        )

    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return LMStudioValidationResult(
            ok=False,
            valid_url=False,
            error_message=f"[FAIL] Malformed LM Studio URL: '{clean_url}'. Must include http:// or https:// and a valid hostname.",
        )

    hostname = parsed.hostname
    port = parsed.port or (443 if parsed.scheme == "https" else 80)

    try:
        socket.getaddrinfo(hostname, port)
        host_resolves = True
    except (socket.gaierror, socket.herror, OSError):
        return LMStudioValidationResult(
            ok=False,
            valid_url=True,
            host_resolves=False,
            hostname=hostname,
            error_message=f"[FAIL] LM Studio hostname could not be resolved: {hostname}",
        )

    resolved_token = token if token is not None else get_lmstudio_token()

    clean_url_stripped = clean_url.rstrip("/")
    if clean_url_stripped.endswith("/models"):
        endpoint = clean_url_stripped
    elif clean_url_stripped.endswith("/v1"):
        endpoint = clean_url_stripped + "/models"
    else:
        endpoint = clean_url_stripped + "/v1/models"

    headers = {"User-Agent": "OpenClaw-PersonalArchive"}
    if resolved_token and str(resolved_token).strip():
        headers["Authorization"] = f"Bearer {str(resolved_token).strip()}"

    req = urllib.request.Request(endpoint, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status_code = resp.status
            raw_body = resp.read()
    except urllib.error.HTTPError as e:
        if e.code == 401:
            return LMStudioValidationResult(
                ok=False,
                valid_url=True,
                host_resolves=True,
                api_responds=False,
                hostname=hostname,
                endpoint=endpoint,
                error_message=(
                    f"[FAIL] LM Studio authentication failed (HTTP 401) at:\n       {endpoint}\n"
                    f"       Set the PERSONAL_ARCHIVIST_LMSTUDIO_API_TOKEN environment variable with a valid token, "
                    f"or disable authentication in LM Studio."
                ),
            )
        return LMStudioValidationResult(
            ok=False,
            valid_url=True,
            host_resolves=True,
            api_responds=False,
            hostname=hostname,
            endpoint=endpoint,
            error_message=f"[FAIL] LM Studio server responded with HTTP {e.code} at:\n       {endpoint}",
        )
    except (urllib.error.URLError, TimeoutError, OSError):
        return LMStudioValidationResult(
            ok=False,
            valid_url=True,
            host_resolves=True,
            api_responds=False,
            hostname=hostname,
            endpoint=endpoint,
            error_message=f"[FAIL] LM Studio server did not respond at:\n       {endpoint}",
        )

    if status_code != 200:
        return LMStudioValidationResult(
            ok=False,
            valid_url=True,
            host_resolves=True,
            api_responds=False,
            hostname=hostname,
            endpoint=endpoint,
            error_message=f"[FAIL] LM Studio server responded with HTTP {status_code} at:\n       {endpoint}",
        )

    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except Exception:
        return LMStudioValidationResult(
            ok=False,
            valid_url=True,
            host_resolves=True,
            api_responds=False,
            hostname=hostname,
            endpoint=endpoint,
            error_message=f"[FAIL] LM Studio server did not return valid JSON from:\n       {endpoint}",
        )

    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        return LMStudioValidationResult(
            ok=False,
            valid_url=True,
            host_resolves=True,
            api_responds=False,
            hostname=hostname,
            endpoint=endpoint,
            error_message=f"[FAIL] LM Studio response lacks expected 'data' array from:\n       {endpoint}",
        )

    model_ids = [m.get("id") for m in payload["data"] if isinstance(m, dict) and "id" in m]

    if model:
        clean_model = model.strip()
        if clean_model not in model_ids:
            return LMStudioValidationResult(
                ok=False,
                valid_url=True,
                host_resolves=True,
                api_responds=True,
                model_available=False,
                hostname=hostname,
                endpoint=endpoint,
                models=model_ids,
                error_message=f"[FAIL] LM Studio is reachable, but model\n       {clean_model}\n       was not returned by /v1/models",
            )
        model_available = True
    else:
        model_available = False

    return LMStudioValidationResult(
        ok=True,
        valid_url=True,
        host_resolves=True,
        api_responds=True,
        model_available=model_available,
        hostname=hostname,
        endpoint=endpoint,
        models=model_ids,
    )


def configure_mcp_server(archive_root, skill_dir, env=None):
    """Configure or update the Personal Archive MCP server transactional entry."""
    proc_env = os.environ if env is None else env

    # Read existing MCP config
    existing_mcp = config_get("mcp.servers.personal-archive")
    existing_env = {}
    if isinstance(existing_mcp, dict) and isinstance(existing_mcp.get("env"), dict):
        existing_env = dict(existing_mcp["env"])

    # 1. Resolve URL
    env_url = proc_env.get("PERSONAL_ARCHIVIST_LMSTUDIO_URL")
    cfg_url = existing_env.get("PERSONAL_ARCHIVIST_LMSTUDIO_URL")
    if env_url and env_url.strip():
        candidate_url = env_url.strip()
    elif cfg_url and cfg_url.strip():
        candidate_url = cfg_url.strip()
    else:
        print("[FAIL] PERSONAL_ARCHIVIST_LMSTUDIO_URL is not configured.", file=sys.stderr)
        return 1

    # 2. Resolve Model
    env_model = proc_env.get("PERSONAL_ARCHIVIST_MODEL")
    cfg_model = existing_env.get("PERSONAL_ARCHIVIST_MODEL")
    if env_model and env_model.strip():
        candidate_model = env_model.strip()
    elif cfg_model and cfg_model.strip():
        candidate_model = cfg_model.strip()
    else:
        print("[FAIL] PERSONAL_ARCHIVIST_MODEL is not configured.", file=sys.stderr)
        return 1

    # 3. Resolve Archive Root
    candidate_root = None
    if archive_root and str(archive_root).strip():
        candidate_root = str(archive_root).strip()
    elif proc_env.get("PERSONAL_ARCHIVE_ROOT") and proc_env["PERSONAL_ARCHIVE_ROOT"].strip():
        candidate_root = proc_env["PERSONAL_ARCHIVE_ROOT"].strip()
    elif existing_env.get("PERSONAL_ARCHIVE_ROOT") and existing_env["PERSONAL_ARCHIVE_ROOT"].strip():
        candidate_root = existing_env["PERSONAL_ARCHIVE_ROOT"].strip()
    else:
        skill_root = config_get(CONFIG_ROOT_KEY)
        if skill_root and str(skill_root).strip():
            candidate_root = str(skill_root).strip()
        else:
            candidate_root = str(Path.home() / "Documents/OpenClaw/PersonalArchive")

    # 4. Resolve Token
    candidate_token = get_lmstudio_token(proc_env=proc_env, cfg_env=existing_env)
    if candidate_token and str(candidate_token).strip():
        candidate_token = str(candidate_token).strip()
    else:
        candidate_token = None

    # 5. Validate candidate values before modifying any config
    val = validate_lmstudio(candidate_url, model=candidate_model, token=candidate_token, timeout=5.0)
    if not val.ok:
        if val.error_message:
            print(val.error_message, file=sys.stderr)
        return 1

    # 6. Build updated MCP server entry preserving existing extra env vars
    updated_env = dict(existing_env)
    updated_env["PERSONAL_ARCHIVE_ROOT"] = candidate_root
    updated_env["PERSONAL_ARCHIVIST_LMSTUDIO_URL"] = candidate_url
    updated_env["PERSONAL_ARCHIVIST_MODEL"] = candidate_model
    if candidate_token:
        updated_env["PERSONAL_ARCHIVIST_LMSTUDIO_API_TOKEN"] = candidate_token

    script_path = str(Path(os.path.expanduser(skill_dir)) / "scripts/mcp_server.py")
    mcp_entry = {
        "command": "python3",
        "args": [script_path],
        "env": updated_env,
    }

    if not config_set("mcp.servers.personal-archive", mcp_entry):
        print("[FAIL] Failed to update mcp.servers.personal-archive configuration.", file=sys.stderr)
        return 1

    # Also keep skills.entries.personal-archive.env.PERSONAL_ARCHIVE_ROOT aligned
    config_set(CONFIG_ROOT_KEY, candidate_root)

    # 7. Enforce archivist tool policy (MCP-only, generic read denied)
    enforce_archivist_tools(candidate_model=candidate_model)

    print(f"[PASS] Personal Archive MCP server configured (URL: {candidate_url}, Model: {candidate_model})")
    return 0


def enforce_archivist_tools(candidate_model=None):
    """Enforce the archivist agent's tool policy in OpenClaw config.

    Ensures:
    - 'read' is removed from allow
    - 'personal-archive/*' is in allow
    - 'read' is explicitly in deny
    - 'exec', 'write', 'group:sessions', 'group:memory', etc. are in deny
    """
    archivist = config_get("agents.entries.archivist")
    default_deny = [
        "read",
        "exec",
        "write",
        "group:sessions",
        "group:memory",
        "web_search",
        "browser",
        "edit",
        "apply_patch",
    ]
    if isinstance(archivist, dict):
        tools = dict(archivist.get("tools") or {})
        allow = [t for t in (tools.get("allow") or []) if t != "read"]
        if "personal-archive/*" not in allow:
            allow.append("personal-archive/*")

        deny = list(tools.get("deny") or [])
        if "read" not in deny:
            deny.insert(0, "read")
        for d in default_deny:
            if d not in deny:
                deny.append(d)

        if tools.get("allow") != allow or tools.get("deny") != deny:
            tools["allow"] = allow
            tools["deny"] = deny
            config_set("agents.entries.archivist.tools", tools)
    else:
        model_name = candidate_model or "lmstudio/google/gemma-4-e4b"
        new_archivist = {
            "name": "Archivist",
            "description": "Isolated factual agent responsible for durable personal records and evidence.",
            "model": model_name,
            "workspace": "~/.openclaw/workspaces/archivist",
            "tools": {
                "allow": ["personal-archive/*"],
                "deny": default_deny,
            },
            "skills": ["personal-archive"],
            "memory": {
                "search": {
                    "rememberAcrossConversations": False,
                },
            },
            "subagents": {
                "allowAgents": [],
            },
        }
        config_set("agents.entries.archivist", new_archivist)


def check(archive_root_arg, skill_dir, workspace_dir, main_agents_path=None, summary_only=False):
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
        and (skill_path / "scripts/mcp_server.py").exists()
        and os.access(skill_path / "scripts/mcp_server.py", os.X_OK)
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
    mcp_server = config_get("mcp.servers.personal-archive")
    mcp_env = mcp_server.get("env", {}) if (isinstance(mcp_server, dict) and isinstance(mcp_server.get("env"), dict)) else {}
    mcp_root = mcp_env.get("PERSONAL_ARCHIVE_ROOT")
    candidate_root = archive_root_arg or (mcp_root if (mcp_root and isinstance(mcp_root, str) and mcp_root.strip()) else None) or configured_root or os.environ.get("PERSONAL_ARCHIVE_ROOT")
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

    # 10. Agent session and exec tool restrictions
    tool_denies = agent.get("tools", {}).get("deny", []) if (isinstance(agent, dict) and isinstance(agent.get("tools"), dict)) else []
    session_tool_ok = "group:sessions" in tool_denies
    results.append(
        ("archivist session tools denied (group:sessions)", session_tool_ok, "critical")
    )
    exec_denied = "exec" in tool_denies
    results.append(
        ("archivist shell execution denied (exec in tools.deny)", exec_denied, "critical")
    )

    # 10a. Agent generic filesystem read denied
    tool_allows = agent.get("tools", {}).get("allow", []) if (isinstance(agent, dict) and isinstance(agent.get("tools"), dict)) else []
    read_denied = ("read" not in tool_allows) and ("read" in tool_denies)
    results.append(
        ("archivist generic filesystem read denied", read_denied, "critical")
    )

    # 10b. Agent allows personal-archive MCP tools
    mcp_allowed = isinstance(tool_allows, list) and any(
        x in tool_allows for x in ("personal-archive/*", "personal-archive", "personal_archive/*")
    )
    results.append(
        ("archivist allows Personal Archive MCP tools (personal-archive/*)", mcp_allowed, "critical")
    )

    # 10c. Personal Archive MCP server registered
    mcp_registered = isinstance(mcp_server, dict) and bool(mcp_server.get("command"))
    results.append(
        ("Personal Archive MCP server registered", mcp_registered, "critical")
    )

    # 10d. MCP environment configuration
    mcp_root_ok = bool(mcp_root and isinstance(mcp_root, str) and mcp_root.strip())
    results.append(
        ("MCP PERSONAL_ARCHIVE_ROOT configured", mcp_root_ok, "critical")
    )

    mcp_url = mcp_env.get("PERSONAL_ARCHIVIST_LMSTUDIO_URL")
    mcp_url_ok = bool(mcp_url and isinstance(mcp_url, str) and mcp_url.strip())
    results.append(
        ("MCP PERSONAL_ARCHIVIST_LMSTUDIO_URL configured", mcp_url_ok, "critical")
    )

    mcp_model = mcp_env.get("PERSONAL_ARCHIVIST_MODEL")
    mcp_model_ok = bool(mcp_model and isinstance(mcp_model, str) and mcp_model.strip())
    results.append(
        ("MCP PERSONAL_ARCHIVIST_MODEL configured", mcp_model_ok, "critical")
    )

    # 10e. LM Studio connectivity and model verification
    val_res = None
    if mcp_url_ok:
        mcp_token = get_lmstudio_token(cfg_env=mcp_env)
        val_res = validate_lmstudio(mcp_url, model=mcp_model if mcp_model_ok else None, token=mcp_token, timeout=5.0)
        host_ok = val_res.host_resolves
        api_ok = val_res.api_responds
        model_ok = val_res.model_available if mcp_model_ok else False
    else:
        host_ok = False
        api_ok = False
        model_ok = False

    results.append(("LM Studio hostname resolves", host_ok, "critical"))
    results.append(("LM Studio API responds", api_ok, "critical"))
    model_desc = f"Vision model {mcp_model} is available" if mcp_model_ok else "Vision model is available"
    results.append((model_desc, model_ok, "critical"))

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
    if main_agents_path:
        main_agents_file = Path(os.path.expanduser(main_agents_path))
    else:
        openclaw_dir = get_openclaw_dir()
        main_agents_file = openclaw_dir / "workspace/AGENTS.md"
    routing_found = False
    if main_agents_file.exists():
        text = main_agents_file.read_text()
        if ROUTING_MARKER in text and "archivist" in text:
            routing_found = True
    results.append(
        (f"Main workspace AGENTS.md contains Personal Archive routing directives ({main_agents_file})", routing_found, "critical")
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
        if not passed and ("LM Studio API responds" in desc or "Vision model" in desc) and val_res and val_res.error_message:
            for err_line in val_res.error_message.splitlines():
                print(f"       {err_line}")
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
    parser.add_argument("--main-agents-file", default=os.environ.get("MAIN_AGENTS_FILE"), help="Path to main agent AGENTS.md")
    parser.add_argument("--summary", action="store_true", help="Quiet summary exit code only")
    parser.add_argument("--configure-mcp", action="store_true", help="Configure Personal Archive MCP server transactionally")
    args = parser.parse_args()

    skill_dir = args.skill_directory or str(get_openclaw_dir() / "workspace/skills/personal-archive")
    workspace_dir = args.workspace_directory or str(get_openclaw_dir() / "workspaces/archivist")

    if args.configure_mcp:
        return configure_mcp_server(args.archive_root, skill_dir)

    return check(args.archive_root, skill_dir, workspace_dir, main_agents_path=args.main_agents_file, summary_only=args.summary)


if __name__ == "__main__":
    sys.exit(main())
