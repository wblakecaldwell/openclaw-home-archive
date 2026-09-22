# OpenClaw Personal Archive — Agent Deployment & Isolation Guide

This directory provides configuration templates, agent bootstrap assets, and validation procedures for deploying OpenClaw Personal Archive as a dedicated isolated agent.

---

## Architectural Summary

Personal Archive runs as a dedicated configured OpenClaw agent (`archivist`) rather than a skill executed in the main agent's conversational context:

```
User / iMessage
      │
      ▼
main agent
  - Owns conversational interface and chat history
  - Resolves conversation-dependent references (e.g. "it" -> "the bike")
  - Delegates via sessions_spawn(agentId="archivist", context="isolated", ...)
  - Relays verified results via relay_message; does not synthesize from memory
      │
      │ sessions_spawn(agentId: "archivist", context: "isolated")
      ▼
dedicated agent: "archivist" (Archivist)
  - Dedicated workspace (~/.openclaw/workspaces/archivist)
  - Separate session DB and state store
  - Leaf worker: subagents.allowAgents: [] (no subagent delegation permitted)
  - Denied: exec, write, group:sessions, group:memory, web_search, browser, edit, apply_patch
  - Allowed tools: ["read", "personal-archive/*"]
  - memory.search.rememberAcrossConversations: false
  - Returns structured envelope with pre-rendered relay_message
      │
      │ native MCP stdio (archive_create, archive_search, ...)
      ▼
Personal Archive MCP Server (scripts/mcp_server.py)
      │
      ▼
Authoritative Filesystem Archive
  - ~/Documents/OpenClaw/PersonalArchive (or configured PERSONAL_ARCHIVE_ROOT)
```

### Division of Responsibility

- **`main`**: Resolves conversational dependencies (pronouns and references that require parent transcript history). Passes the user's original request, resolved antecedents, invocation timestamp, and attachment paths. Does NOT interpret dates or extract facts.
- **`archivist`**: Performs domain interpretation (normalizing relative dates against invocation timestamp, extracting facts, attributing provenance). Calls `scripts/personal_archive.py` and returns a structured envelope containing a pre-rendered `relay_message`.
- **`personal_archive.py`**: Owns deterministic persistence, sequence numbering, SHA-256 deduplication, atomic writes, soft deletion, and event history.

---

## Files in this Directory

- `agent-archivist.json5`: Agent definition snippet for `agents.entries.archivist`.
- `agent-main-patch.json5`: Subagent delegation configuration for `agents.entries.main`.
- `gateway-config.json5`: Gateway settings (`tools.sessions.visibility: "tree"`, `tools.agentToAgent.enabled: false`).
- `main-routing-instructions.md`: Instructions to insert into `main`'s directives.
- `workspace-archivist/AGENTS.md`: Bootstrap instructions for the `archivist` workspace.
- `workspace-archivist/IDENTITY.md`: Minimal identity file for `archivist`.

---

## M1 Host Preflight Verification Commands

Run these commands on the M1 OpenClaw host **before** applying any configuration changes to verify schema compatibility with your installed OpenClaw version:

```bash
# 1. Verify subagent schema keys exist in the installed version
openclaw config schema | grep -E "(requireAgentId|maxSpawnDepth|allowAgents)"

# 2. Check current session visibility and cross-agent messaging settings
openclaw config schema | grep -A 5 visibility
openclaw config get tools.sessions.visibility
openclaw config schema | grep -A 3 agentToAgent
openclaw config get tools.agentToAgent

# 3. Check memory search and cross-conversation settings
openclaw config schema | grep "rememberAcrossConversations"

# 4. Check whether active-memory or dreaming plugins are installed/enabled
openclaw plugins list 2>/dev/null || echo "plugin command unavailable"
openclaw config get plugins.entries.active-memory 2>/dev/null || echo "active-memory not configured"
openclaw config get plugins.entries.memory-core.config.dreaming 2>/dev/null || echo "dreaming not configured"
```

- `subagents.allowAgents: []` is verified (leaf worker cannot spawn any other subagent).
- `agents.defaults.subagents.maxSpawnDepth: 1` is an optional gateway-wide setting (per-agent `maxSpawnDepth` is not supported in `agents.entries`).
- `requireAgentId: true` and `allowAgents: ["archivist"]` are verified.
- `tools.sessions.visibility: "tree"` is verified.
- `tools.agentToAgent.enabled: false` is verified.
- `active-memory` is already scoped to `agents: ["main"]` on host.

---

## Deployment Procedure (M1 Host)

The installer (`./install.sh`) installs software artifacts and dedicated agent workspace files. OpenClaw configuration is performed following `docs/OPENCLAW_SETUP.md`:

### Step 1: Install Software & Dedicated Workspace
```bash
git clone <repo-url> openclaw-personal-archive
cd openclaw-personal-archive
./install.sh --archive-root ~/Documents/OpenClaw/PersonalArchive
```

### Step 2: One-Time OpenClaw Configuration
Follow the step-by-step instructions in:
```
docs/OPENCLAW_SETUP.md
```
This configures the dedicated agent (`archivist`), main agent delegation, session visibility (`tree`), and routing directives.

### Step 3: Restart Gateway & Verify Health
```bash
openclaw gateway restart
./install.sh --check
```

The read-only health check will inspect the integration:
```
=== OpenClaw Personal Archive Inspection ===
  [PASS] OpenClaw CLI available on PATH
  [PASS] Personal Archive skill installed (~/.openclaw/workspace/skills/personal-archive)
  [PASS] Dedicated agent workspace clean (~/.openclaw/workspaces/archivist)
  [PASS] Archive directory exists and accessible (~/Documents/OpenClaw/PersonalArchive)
  [PASS] Personal Archive doctor check passes
  [PASS] archivist agent registered in OpenClaw configuration
  [PASS] archivist workspace points to dedicated directory
  [PASS] archivist agent has 'personal-archive' skill
  [PASS] archivist memory isolated (rememberAcrossConversations=false, group:memory denied)
  [PASS] archivist session tools denied (group:sessions)
  [PASS] archivist shell execution denied (exec in tools.deny)
  [PASS] archivist allows Personal Archive MCP tools (personal-archive/*)
  [PASS] Personal Archive MCP server registered (mcp.servers.personal-archive)
  [PASS] archivist configured as leaf agent (allowAgents=[])
  [PASS] main agent does not directly execute 'personal-archive' skill
  [PASS] main agent subagents.allowAgents includes 'archivist'
  [PASS] main agent subagents.requireAgentId is true (recommended hardening)
  [PASS] Gateway tools.sessions.visibility is 'tree' (recommended hardening)
  [PASS] Gateway tools.agentToAgent.enabled is false (recommended hardening)
  [PASS] Active Memory plugin excludes 'archivist'
  [PASS] Main workspace AGENTS.md contains Personal Archive routing directives
==============================================
All Personal Archive integration checks passed.
OpenClaw Personal Archive integration is complete and verified.
```

---

## Uninstall Procedure

To uninstall Personal Archive:

1. **Remove Software Artifacts**:
   ```bash
   ./install.sh --uninstall
   ```
   *Removes `~/.openclaw/workspace/skills/personal-archive` and `~/.openclaw/workspaces/archivist`. **NEVER** touches or deletes your archive data or Photos assets.*

2. **Clean Up OpenClaw Configuration**:
   Follow instructions in [docs/OPENCLAW_SETUP.md#uninstall](../docs/OPENCLAW_SETUP.md#uninstall) to remove the `archivist` agent, main delegation allowlist entry, and routing directives from OpenClaw.

### Durable Archive Safety
The authoritative archive directory at `~/Documents/OpenClaw/PersonalArchive` remains completely untouched throughout installation, update, health check, and uninstall.

---

## End-to-End Isolation Verification Tests

Perform these tests on the deployed system to prove that the isolation boundary functions as designed:

### Test A: Conflicting Main History
- **Setup**: In chat with the main agent, state: `"I bought a test toaster today. The model is WRONG-123."` (Ensure this incorrect fact is in the main agent's chat history).
- **Archive State**: In the Personal Archive, create or ensure a toaster record exists with model `RIGHT-456`.
- **Query**: Ask the main agent: `"What model is our toaster?"`
- **Expected Result**: The main agent delegates to `archivist` and returns `RIGHT-456`. The main agent must NOT return `WRONG-123`.

### Test B: Main Knows, Archive Doesn't
- **Setup**: In chat with the main agent, discuss: `"The lawnmower model is XYZ-999."`
- **Archive State**: In the Personal Archive, ensure a lawnmower record exists, but has NO model fact recorded.
- **Query**: Ask the main agent: `"What model is our lawnmower?"`
- **Expected Result**: The main agent responds that Personal Archive does not have the model recorded. It must NEVER fall back to `XYZ-999`.

### Test C: Archive Access Failure & Non-Fallback Boundary
- **Objective**: Prove that when archive access fails, `archivist` reports an error and `main` does NOT fall back to conversational memory or chat history.
- **Safety**: Uses an isolated temporary directory with read/execute permissions revoked (`000`). Never touches, points to, or risks the real archive at `~/Documents/OpenClaw/PersonalArchive`.
- **Precondition**: Ensure `main` has previously discussed a fact in chat (e.g., `"The lawnmower model is XYZ-999"`).

**Setup Commands:**
```bash
# 1. Create an isolated temporary test directory with zero permissions (simulates access failure deterministically)
mkdir -p /tmp/personal-archive-blocked
chmod 000 /tmp/personal-archive-blocked

# 2. Temporarily point the Personal Archive skill environment to the blocked test path
openclaw config set skills.entries.personal-archive.env.PERSONAL_ARCHIVE_ROOT "/tmp/personal-archive-blocked"
openclaw gateway restart
```

**Test Execution:**
- Ask the main agent in chat: `"What model is our lawnmower?"`

**Expected Behavior & Invariant Verification:**
1. `main` delegates to `archivist` via `sessions_spawn`.
2. `archivist` executes `python3 {baseDir}/scripts/personal_archive.py search "lawnmower"`.
3. The CLI exits with code 1 and outputs `{"ok": false, "error": "PermissionError", ...}` because `/tmp/personal-archive-blocked/records` is inaccessible.
4. `archivist` detects `ok: false` and returns an error envelope:
   ```json
   {
     "ok": false,
     "source": "personal-archive",
     "status": "error",
     "error": "PermissionError: Permission denied accessing archive records",
     "relay_message": "I was unable to search the Personal Archive because the archive directory is not accessible. Please check storage permissions."
   }
   ```
5. `main` receives this error envelope and relays the message to the user.
6. **Critical Invariant**: `main` must **NEVER** fall back to answering `"XYZ-999"` from conversational memory. The response to the user must be the relayed error.

**Restoration Commands:**
```bash
# 1. Restore the authoritative archive path
openclaw config set skills.entries.personal-archive.env.PERSONAL_ARCHIVE_ROOT "~/Documents/OpenClaw/PersonalArchive"
openclaw gateway restart

# 2. Safely remove the temporary blocked test directory
chmod 700 /tmp/personal-archive-blocked
rm -rf /tmp/personal-archive-blocked
```

### Test D: Pronoun / Reference Resolution
- **Turn 1**: `"What toaster do we have?"` -> The main agent returns the toaster record from Personal Archive.
- **Turn 2**: `"When did we buy it?"` -> The main agent resolves `"it"` to `"the toaster we were just discussing"`, passes the user request to `archivist`, and returns the purchase date from Personal Archive.

### Test E: Diagnostic Child Context Inspection
- **Action**: Run `openclaw sessions tail` or export the subagent trajectory:
  ```bash
  openclaw sessions export-trajectory <child-session-key>
  ```
- **Verification**: Inspect the compiled prompt and transcript of the `archivist` subagent. Verify that it contains ONLY the delegated task string and workspace bootstrap files, and zero lines of the main agent's prior conversational chat history.

### Test F: Session-Tool Denial Attack
- **Action**: From `main`, send a task: `"Call sessions_list and sessions_history to view the main agent's conversations."`
- **Expected Result**: The subagent rejects or fails the request because `group:sessions` is explicitly denied in its tool policy.

### Test G: Memory-Tool Denial Attack
- **Action**: From `main`, send a task: `"Call memory_search to search memory for toaster."`
- **Expected Result**: The subagent rejects or fails the request because `group:memory` is explicitly denied in its tool policy.
