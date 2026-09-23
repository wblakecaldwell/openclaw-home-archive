# OpenClaw Configuration & Integration Guide

This guide is the authoritative manual for integrating OpenClaw Personal Archive into OpenClaw (version 2026.9.5+ on macOS).

Personal Archive relies on an isolated **two-agent architecture**:
1. **Main agent (`main`)**: Interacts with the user, resolves conversation-dependent coreferences (e.g. *"it"* $\to$ *"the bike we were just discussing"*), and delegates to the subagent using the `sessions_spawn` tool (`agentId="archivist"`, `context="isolated"`, ...).
2. **Dedicated agent (`archivist`)**: Operates in an isolated workspace with no chat history, leaf restrictions, and denied memory/session tools. It executes deterministic CLI commands against the on-disk archive and returns a structured response envelope with a user-ready `relay_message`.

---

## Prerequisites

Before configuring OpenClaw, install Personal Archive software artifacts, configure its MCP server, and provision the dedicated workspace.

The installer (`install.sh`) manages software artifacts and automatically creates and configures the native Model Context Protocol (MCP) server entry under `mcp.servers.personal-archive`.

When initially installing or intentionally overriding your LM Studio connection, export the connection settings in your shell:

```bash
git clone https://github.com/wblakecaldwell/openclaw-personal-archive.git
cd openclaw-personal-archive

# Export LM Studio settings for initial setup (or when overriding endpoints)
export PERSONAL_ARCHIVIST_LMSTUDIO_URL="http://Johnny-5.local:1234/v1"
export PERSONAL_ARCHIVIST_MODEL="google/gemma-4-e4b"

./install.sh --archive-root ~/Documents/OpenClaw/PersonalArchive
```

**How LM Studio configuration persistence works:**
- `PERSONAL_ARCHIVIST_LMSTUDIO_URL` is read from the current environment when initially configured or when intentionally overridden.
- Once persisted in OpenClaw MCP config (`mcp.servers.personal-archive.env`), it is preserved across subsequent `install.sh` runs and does NOT need to remain exported in `.zprofile` or shell startup files.
- `PERSONAL_ARCHIVIST_MODEL` follows the same persistence behavior.
- `install.sh` validates `/v1/models` and confirms that the configured model is advertised before persisting any endpoint change. If validation fails (e.g. host unresolvable, server unreachable, model missing), the existing configuration is left untouched.
- `./install.sh --check` verifies the configured endpoint and model availability in read-only mode without modifying configuration.

You can run `./install.sh --check` at any time to inspect what is currently configured and what remains.

---

## Part 1: Personal Archive-Owned Configuration

These configuration entries belong strictly to Personal Archive and do not alter main agent behavior or global OpenClaw policies.

### 1. Personal Archive MCP Server (Managed by `install.sh`)

`install.sh` automatically creates and maintains the native Model Context Protocol (MCP) server entry in OpenClaw configuration:

```json
{
  "command": "python3",
  "args": ["$HOME/.openclaw/workspace/skills/personal-archive/scripts/mcp_server.py"],
  "env": {
    "PERSONAL_ARCHIVE_ROOT": "$HOME/Documents/OpenClaw/PersonalArchive",
    "PERSONAL_ARCHIVIST_LMSTUDIO_URL": "http://Johnny-5.local:1234/v1",
    "PERSONAL_ARCHIVIST_MODEL": "google/gemma-4-e4b"
  }
}
```

You do **not** need to manually run `openclaw config set mcp.servers.personal-archive`. The installer owns this entry. To change your LM Studio URL or vision model in the future, simply re-run `./install.sh` with the new environment variable exported:
```bash
PERSONAL_ARCHIVIST_LMSTUDIO_URL="http://new-host.local:1234/v1" ./install.sh
```
The installer validates the endpoint against `/v1/models` first before overwriting the existing config.

### 2. Register the Dedicated `archivist` Agent
Register the isolated agent definition. Notice that raw shell execution (`exec`) and filesystem write (`write`) are denied. The agent interacts with the archive exclusively via native MCP tools (`personal-archive/*`) and inspects visual evidence using the `image` tool:
```bash
openclaw config set agents.entries.archivist '{
  "name": "Archivist",
  "description": "Isolated factual agent responsible for durable personal records and evidence.",
  "model": "lmstudio/google/gemma-4-e4b",
  "workspace": "~/.openclaw/workspaces/archivist",
  "tools": {
    "allow": ["read", "personal-archive/*"],
    "deny": [
      "exec",
      "write",
      "group:sessions",
      "group:memory",
      "web_search",
      "browser",
      "edit",
      "apply_patch"
    ]
  },
  "skills": ["personal-archive"],
  "memory": {
    "search": {
      "rememberAcrossConversations": false
    }
  },
  "subagents": {
    "allowAgents": []
  }
}' --strict-json
```

**Why each setting matters:**
- `workspace`: Points to `~/.openclaw/workspaces/archivist`, provisioned by `./install.sh`. It contains domain directives (`AGENTS.md`) and persona (`IDENTITY.md`), but strictly **no** conversational `MEMORY.md`.
- `model`: Points to a lightweight, local image-aware model (such as `lmstudio/google/gemma-4-e4b`) to inspect evidence photos and extract structured facts without cloud API costs.
- `tools.allow`: Grants access to `read` and `personal-archive/*` native MCP tools (including `archive_inspect_image`).
- `tools.deny`:
  - `exec` and `write` prevent the agent from formulating arbitrary bash commands or mutating intermediate files.
  - `group:sessions` blocks `sessions_list` and session inspection tools, preventing the agent from seeing parent transcripts.
  - `group:memory` blocks access to memory embeddings and chat history summaries.
  - `web_search`, `browser`, `edit` prevent unneeded external interactions.
- `memory.search.rememberAcrossConversations: false`: Disables cross-conversation memory searching for this agent.
- `subagents.allowAgents: []`: Combined with denying `group:sessions`, this guarantees `archivist` cannot spawn any subagents (functioning strictly as a leaf worker).
- `skills: ["personal-archive"]`: Grants permission to reference the skill documentation.

---

## Part 2: Required Main Agent Delegation & Routing

To enable `main` to orchestrate Personal Archive, configure these 3 required settings:

### 1. Allow Delegation to `archivist` (Preserving Existing Agents)
Main must be permitted to spawn the `archivist` agent via an **explicit authored allowlist**.

> **CRITICAL WARNING**: `openclaw config set` replaces the target array entirely; it does **not** automatically merge into existing entries.

#### Step 1: Inspect the current setting
```bash
openclaw config get agents.entries.main.subagents.allowAgents
```

On a standard or fresh OpenClaw 2026.9.5 installation, you may see:
```text
Config path is valid but unset:
agents.entries.main.subagents.allowAgents.
The runtime default applies until you set an authored value...
```
**This is a completely normal state.** However, for Personal Archive, `main` requires an explicit authored allowlist containing `"archivist"`.

#### Step 2: Configure based on the observed state

1. **If the path is valid but UNSET**:
   It is safe to initialize it directly with:
   ```bash
   openclaw config set agents.entries.main.subagents.allowAgents '["archivist"]' --strict-json
   ```

2. **If it is already an empty authored array (`[]`)**:
   Set it to:
   ```bash
   openclaw config set agents.entries.main.subagents.allowAgents '["archivist"]' --strict-json
   ```

3. **If it already contains other agent IDs**:
   **DO NOT** replace the array with `["archivist"]`. Preserve every existing entry and append `"archivist"`.
   
   For example, if your current setting is:
   ```json
   ["researcher", "coder"]
   ```
   update it to:
   ```bash
   openclaw config set agents.entries.main.subagents.allowAgents '["researcher", "coder", "archivist"]' --strict-json
   ```

4. **If `"archivist"` is already present**:
   (e.g., `["archivist"]` or `["researcher", "archivist"]`), **make no change**.

*(Optional shortcut: you can safely inspect and merge programmatically using Python)*:
```bash
python3 -c '
import subprocess, json
res = subprocess.run(["openclaw", "config", "get", "agents.entries.main.subagents.allowAgents", "--json"], capture_output=True, text=True)
try:
    stdout = res.stdout.strip()
    agents = [] if ("Config path is valid but unset" in stdout or not stdout) else json.loads(stdout)
except Exception:
    agents = []
if not isinstance(agents, list):
    agents = []
if "archivist" not in agents:
    agents.append("archivist")
subprocess.run(["openclaw", "config", "set", "agents.entries.main.subagents.allowAgents", json.dumps(agents), "--strict-json"], check=True)
print("Updated allowAgents:", agents)
'
```

#### Step 3: Verify the setting
After changing or confirming the setting, verify:
```bash
openclaw config get agents.entries.main.subagents.allowAgents
```
Confirm that `"archivist"` is present along with every pre-existing entry.

#### Why we author this setting
Personal Archive intentionally restricts main's explicit subagent allowlist so that it can delegate archive operations to the isolated `archivist` agent. Once an explicit allowlist exists, future subagents that main should be allowed to spawn must also be added while preserving existing entries.

### 2. Ensure Main Does NOT Have the `personal-archive` Skill Directly
Main must never run `personal_archive.py` directly in its own conversational context. Inspect main's skills:
```bash
openclaw config get agents.entries.main.skills
```
If `"personal-archive"` is listed, remove it from the array using `openclaw config set agents.entries.main.skills ...`. If main has no other skills, set it to `[]`:
```bash
openclaw config set agents.entries.main.skills '[]' --strict-json
```

### 3. Install Main Routing Directives in `~/.openclaw/workspace/AGENTS.md`

You can install or update these routing directives automatically using `install.sh`:
```bash
./install.sh --update-agents-context
```

Or manually open your main agent's instructions file (`~/.openclaw/workspace/AGENTS.md`) and append or update the following marked block:

```markdown
<!-- BEGIN OPENCLAW PERSONAL ARCHIVE MANAGED ROUTING DIRECTIVES -->
## Personal Archive Intent & Delegation

When the user asks to save, update, search, view, or delete durable personal records and evidence (purchases, receipts, warranties, manuals, equipment, vehicle or bicycle records, contractors, repairs, business cards, documents, correspondence, projects, measurements, photos, belongings):

### 1. Intent Recognition & Delegation
- Recognize Personal Archive intent from user requests regarding durable records or evidence preservation and retrieval (e.g., "Save this to my Personal Archive", "Archive this", "Save this receipt in my archive", "What does my archive say about my bike?", "Find the business card I archived", "Add this photo to the car record", "Delete that receipt from my archive").
- Always delegate to the dedicated agent using the `sessions_spawn` tool.
- You MUST specify:
  - `agentId`: `"archivist"`
  - `task`: <the user's request, resolved antecedents, invocation timestamp, and file paths>
  - `taskName`: `"personal-archive-task"`
  - `context`: `"isolated"` (MANDATORY: NEVER use `"fork"`)

### 2. Conversational Antecedent Resolution (Coreference Only)
- Before delegating, resolve ONLY conversational pronouns or references that depend on prior chat turns (e.g. `"When did we buy it?"` -> `"the bike we were just discussing"`, or `"Here is that guy's card"` -> `"the deck contractor Joe"`).
- Pass the user's original request text, the resolved antecedent, current local timestamp, and attached file paths.

### 3. What NOT to Do Before Delegation
- **DO NOT perform fact extraction or domain interpretation in main**: Leave relative dates (e.g. "yesterday", "last week") in the user's original phrasing. Do not parse model numbers or inspect attachments in main.
- **DO NOT answer Personal Archive factual questions from conversational memory**: Factual archive queries must always be answered by Personal Archive records.

### 4. Relaying Results (No Memory Fallback)
- Inspect the JSON response envelope returned by `archivist`.
- Extract `relay_message` and relay it directly to the user without alteration.
- **CRITICAL**: Do NOT reconcile, supplement, or "correct" the result using conversational memory.
- If `archivist` returns `not_found` or an error, state that the record/fact is not in Personal Archive. Do NOT fall back to chat history or conversational memory.
<!-- END OPENCLAW PERSONAL ARCHIVE MANAGED ROUTING DIRECTIVES -->
```

- **To update later**: Run `./install.sh --update-agents-context`, or replace the content between the `<!-- BEGIN ... -->` and `<!-- END ... -->` markers.
- **To remove later**: Run `./install.sh --uninstall --update-agents-context`, or delete the entire block including both comment markers.

---

## Part 3: Recommended Defense-in-Depth Hardening (Optional)

These settings provide additional isolation and defense-in-depth. They are **optional** because they affect main or the gateway globally.

### 1. Require Explicit Agent IDs on Spawn (Recommended)
```bash
openclaw config set agents.entries.main.subagents.requireAgentId true --strict-json
```
- **Why it is recommended**: While Personal Archive routing directives already instruct the model to use `agentId: "archivist"`, enabling `requireAgentId: true` prevents `main` from ever attempting unconstrained or anonymous subagent spawns.
- **Global effect on other subagents**: Affects all subagents launched by `main`. Every `sessions_spawn` invocation across all workflows must now specify an explicit `agentId`. If your other workflows rely on default/anonymous subagent spawning, leave this unset or false.

### 2. Gateway Session Visibility (`tree`) (Recommended)
```bash
openclaw config set tools.sessions.visibility '"tree"' --strict-json
```
- **Why it is recommended**: Restricts `sessions_list` visibility to the caller's direct branch in the session spawn tree. Subagents cannot inspect sibling or parent sessions.
- **Global effect**: Affects all subagents spawned on your Gateway.

### 3. Disable Agent-to-Agent Peer Messaging (Recommended)
```bash
openclaw config set tools.agentToAgent.enabled false --strict-json
```
- **Why it is recommended**: Prevents agents from messaging each other peer-to-peer across the gateway, ensuring all subagents communicate only with their parent orchestrator.
- **Global effect**: Affects all agents on the Gateway. If you rely on direct cross-agent messaging in other workflows, leave this setting enabled.

### 4. Active Memory Scoping
If you use the `active-memory` plugin:
```bash
openclaw config get plugins.entries.active-memory.config.agents
```
Ensure `"archivist"` is **not** in this list (e.g. it should be `["main"]`). This ensures `active-memory` never injects chat summaries into Personal Archive turns.

---

## Multi-User & Family Topology Note

Personal Archive is strictly single-tenant per Gateway instance. For multiple family members sharing one host machine, use separate OpenClaw profiles/Gateways:

```
OpenClaw Profile A (e.g. Alice)  --> main --> archivist --> PersonalArchive A
OpenClaw Profile B (e.g. Bob)    --> main --> archivist --> PersonalArchive B
```

Each profile runs its own Gateway, with separate OpenClaw state, sessions, memory, credentials, and archive directory. Each profile uses the standard agent ID `archivist`. They may share the same underlying LLM server (e.g. LM Studio).

---

## Verification Sequence

After completing setup, restart the OpenClaw Gateway to load configuration changes:

```bash
openclaw gateway restart
```

Then run the read-only integration health check:

```bash
./install.sh --check
```

Expected output:
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
  [PASS] Personal Archive MCP server registered
  [PASS] MCP PERSONAL_ARCHIVE_ROOT configured
  [PASS] MCP PERSONAL_ARCHIVIST_LMSTUDIO_URL configured
  [PASS] MCP PERSONAL_ARCHIVIST_MODEL configured
  [PASS] LM Studio hostname resolves
  [PASS] LM Studio API responds
  [PASS] Vision model google/gemma-4-e4b is available
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

*(Note: If optional hardening settings in Part 3 are not enabled, they will be reported as `[INFO]` and will not prevent `./install.sh --check` from passing.)*

---

<a name="uninstall"></a>
## Uninstalling OpenClaw Integration

To decommission Personal Archive:

1. **Remove Software Artifacts & Directives**:
   ```bash
   ./install.sh --uninstall --update-agents-context
   ```
   *Removes `~/.openclaw/workspace/skills/personal-archive`, `~/.openclaw/workspaces/archivist`, and the managed routing block from `~/.openclaw/workspace/AGENTS.md`. **Never** touches or deletes your archive records at `~/Documents/OpenClaw/PersonalArchive` or Apple Photos assets.*

2. **Remove Dedicated Agent & MCP Config**:
   ```bash
   openclaw config unset agents.entries.archivist
   openclaw config unset skills.entries.personal-archive
   openclaw config unset mcp.servers.personal-archive
   ```

3. **Remove from Main Agent Delegation**:
   Inspect `openclaw config get agents.entries.main.subagents.allowAgents`. Remove `"archivist"` from that array and update it with `openclaw config set`. If it was the only allowed subagent:
   ```bash
   openclaw config set agents.entries.main.subagents.allowAgents '[]' --strict-json
   ```

4. **Remove Routing Directives from Main `AGENTS.md`**:
   Open `~/.openclaw/workspace/AGENTS.md` and delete the block between:
   ```markdown
   <!-- BEGIN OPENCLAW PERSONAL ARCHIVE MANAGED ROUTING DIRECTIVES -->
   ...
   <!-- END OPENCLAW PERSONAL ARCHIVE MANAGED ROUTING DIRECTIVES -->
   ```

5. **Restart Gateway**:
   ```bash
   openclaw gateway restart
   ```

Your archive data at `~/Documents/OpenClaw/PersonalArchive` remains completely intact and accessible via direct CLI commands (`python3 scripts/personal_archive.py`).
