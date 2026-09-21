# OpenClaw Configuration & Integration Guide

This guide is the authoritative manual for integrating OpenClaw Home Archive into OpenClaw (version 2026.9.5+ on macOS).

Home Archive relies on an isolated **two-agent architecture**:
1. **Main agent (`main`)**: Interacts with the user, resolves conversation-dependent coreferences (e.g. *"it"* $\to$ *"the toaster we were just discussing"*), and delegates to the subagent using `sessions_spawn(agentId="home-archive", context="isolated", ...)`.
2. **Dedicated agent (`home-archive`)**: Operates in an isolated workspace with no chat history, leaf restrictions, and denied memory/session tools. It executes deterministic CLI commands against the on-disk archive and returns a structured response envelope with a user-ready `relay_message`.

---

## Prerequisites

Before configuring OpenClaw, install Home Archive software artifacts and provision the dedicated workspace:

```bash
git clone https://github.com/wblakecaldwell/openclaw-home-archive.git
cd openclaw-home-archive
./install.sh --archive-root ~/Documents/OpenClaw/HomeArchive
```

You can run `./install.sh --check` at any time to inspect what is currently configured and what remains.

---

## Part 1: Home Archive-Owned Configuration

These configuration entries belong strictly to Home Archive and do not alter main agent behavior or global OpenClaw policies.

### 1. Set Archive Location for the Skill
Set the path to the durable household archive outside this repository:
```bash
openclaw config set skills.entries.home-archive.env.HOME_ARCHIVE_ROOT "~/Documents/OpenClaw/HomeArchive"
```

### 2. Register the Dedicated `home-archive` Agent
Register the isolated agent definition:
```bash
openclaw config set agents.entries.home-archive '{
  "name": "Home Archive Agent",
  "description": "Isolated factual agent responsible for durable household records and evidence.",
  "workspace": "~/.openclaw/workspaces/home-archive",
  "tools": {
    "allow": ["read", "write", "exec", "image"],
    "deny": [
      "group:sessions",
      "group:memory",
      "web_search",
      "browser",
      "edit",
      "apply_patch"
    ]
  },
  "skills": ["home-archive"],
  "memory": {
    "search": {
      "rememberAcrossConversations": false
    }
  },
  "subagents": {
    "maxSpawnDepth": 1,
    "allowAgents": []
  }
}' --strict-json
```

**Why each setting matters:**
- `workspace`: Points to `~/.openclaw/workspaces/home-archive`, provisioned by `./install.sh`. It contains domain directives (`AGENTS.md`) and persona (`IDENTITY.md`), but strictly **no** conversational `MEMORY.md`.
- `tools.deny`:
  - `group:sessions` blocks `sessions_list` and session inspection tools, preventing the agent from seeing parent transcripts.
  - `group:memory` blocks access to memory embeddings and chat history summaries.
  - `web_search`, `browser`, `edit` prevent unneeded external interactions.
- `memory.search.rememberAcrossConversations: false`: Disables cross-conversation memory searching for this agent.
- `subagents.maxSpawnDepth: 1`: In OpenClaw's schema, `1` makes direct children leaves. Combined with `allowAgents: []`, this guarantees this subagent cannot spawn further subagents.
- `skills: ["home-archive"]`: Grants permission to execute `home_archive.py`.

---

## Part 2: Required Main Agent Delegation & Routing

To enable `main` to orchestrate Home Archive, configure these 3 required settings:

### 1. Allow Delegation to `home-archive` (Preserving Existing Agents)
Main must be permitted to spawn the `home-archive` agent.

> **IMPORTANT**: `openclaw config set` replaces the entire array. It does **not** automatically merge.

First, inspect your current list of allowed subagents:
```bash
openclaw config get agents.entries.main.subagents.allowAgents
```

- **If the output is empty or unset (`[]` or `null`)**, run:
  ```bash
  openclaw config set agents.entries.main.subagents.allowAgents '["home-archive"]' --strict-json
  ```

- **If you already have allowed agents** (e.g. `["code-assistant"]`), preserve them and append `"home-archive"`:
  ```bash
  openclaw config set agents.entries.main.subagents.allowAgents '["code-assistant", "home-archive"]' --strict-json
  ```

*(Optional shortcut: you can safely merge programmatically using Python)*:
```bash
python3 -c '
import subprocess, json
res = subprocess.run(["openclaw", "config", "get", "agents.entries.main.subagents.allowAgents", "--json"], capture_output=True, text=True)
try: agents = json.loads(res.stdout) if res.returncode == 0 else []
except Exception: agents = []
if not isinstance(agents, list): agents = []
if "home-archive" not in agents: agents.append("home-archive")
subprocess.run(["openclaw", "config", "set", "agents.entries.main.subagents.allowAgents", json.dumps(agents), "--strict-json"], check=True)
print("Updated allowAgents:", agents)
'
```

### 2. Ensure Main Does NOT Have the `home-archive` Skill Directly
Main must never run `home_archive.py` directly in its own conversational context. Inspect main's skills:
```bash
openclaw config get agents.entries.main.skills
```
If `"home-archive"` is listed, remove it from the array using `openclaw config set agents.entries.main.skills ...`. If main has no other skills, set it to `[]`:
```bash
openclaw config set agents.entries.main.skills '[]' --strict-json
```

### 3. Install Main Routing Directives in `~/.openclaw/workspace/AGENTS.md`
Open your main agent's instructions file (`~/.openclaw/workspace/AGENTS.md`) and append the following marked block:

```markdown
<!-- BEGIN OPENCLAW HOME ARCHIVE MANAGED ROUTING DIRECTIVES -->
## Home Archive Intent & Delegation

When the user asks to save, update, search, view, or delete durable household information (appliances, receipts, manuals, warranties, contractors, repairs, dimensions, paint colors, home projects):

### 1. Intent Recognition & Delegation
- Recognize Home Archive intent from user requests regarding durable household records.
- Always delegate to the dedicated agent via `sessions_spawn`.
- You MUST specify:
  - `agentId`: `"home-archive"`
  - `context`: `"isolated"` (MANDATORY: NEVER use `"fork"`)
  - `taskName`: `"home-archive-task"`

### 2. Conversational Antecedent Resolution (Coreference Only)
- Before delegating, resolve ONLY conversational pronouns or references that depend on prior chat turns (e.g. `"When did we buy it?"` -> `"the toaster we were just discussing"`, or `"Here is that guy's card"` -> `"the deck contractor Joe"`).
- Pass the user's original request text, the resolved antecedent, current local timestamp, and attached file paths.

### 3. What NOT to Do Before Delegation
- **DO NOT perform fact extraction or domain interpretation in main**: Leave relative dates (e.g. "yesterday", "last week") in the user's original phrasing. Do not parse model numbers or inspect attachments in main.
- **DO NOT answer Home Archive factual questions from conversational memory**: Factual household queries must always be answered by Home Archive records.

### 4. Relaying Results (No Memory Fallback)
- Inspect the JSON response envelope returned by `home-archive`.
- Extract `relay_message` and relay it directly to the user without alteration.
- **CRITICAL**: Do NOT reconcile, supplement, or "correct" the result using conversational memory.
- If `home-archive` returns `not_found` or an error, state that the record/fact is not in Home Archive. Do NOT fall back to chat history or conversational memory.
<!-- END OPENCLAW HOME ARCHIVE MANAGED ROUTING DIRECTIVES -->
```

- **To update later**: Replace the content between the `<!-- BEGIN ... -->` and `<!-- END ... -->` markers.
- **To remove later**: Delete the entire block including both comment markers.

---

## Part 3: Recommended Defense-in-Depth Hardening (Optional)

These settings provide additional isolation and defense-in-depth. They are **optional** because they affect main or the gateway globally.

### 1. Require Explicit Agent IDs on Spawn (Recommended)
```bash
openclaw config set agents.entries.main.subagents.requireAgentId true --strict-json
```
- **Why it is recommended**: While Home Archive routing directives already instruct the model to use `agentId: "home-archive"`, enabling `requireAgentId: true` prevents `main` from ever attempting unconstrained or anonymous subagent spawns.
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
Ensure `"home-archive"` is **not** in this list (e.g. it should be `["main"]`). This ensures `active-memory` never injects chat summaries into Home Archive turns.

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
=== OpenClaw Home Archive Inspection ===
  [PASS] OpenClaw CLI available on PATH
  [PASS] Home Archive skill installed (~/.openclaw/workspace/skills/home-archive)
  [PASS] Dedicated agent workspace clean (~/.openclaw/workspaces/home-archive)
  [PASS] Archive directory exists and accessible (~/Documents/OpenClaw/HomeArchive)
  [PASS] Home Archive doctor check passes
  [PASS] home-archive agent registered in OpenClaw configuration
  [PASS] home-archive workspace points to dedicated directory
  [PASS] home-archive agent has 'home-archive' skill
  [PASS] home-archive memory isolated (rememberAcrossConversations=false, group:memory denied)
  [PASS] home-archive session tools denied (group:sessions)
  [PASS] home-archive configured as leaf agent (maxSpawnDepth=1, allowAgents=[])
  [PASS] main agent does not directly execute 'home-archive' skill
  [PASS] main agent subagents.allowAgents includes 'home-archive'
  [PASS] main agent subagents.requireAgentId is true (recommended hardening)
  [PASS] Gateway tools.sessions.visibility is 'tree' (recommended hardening)
  [PASS] Gateway tools.agentToAgent.enabled is false (recommended hardening)
  [PASS] Active Memory plugin excludes 'home-archive'
  [PASS] Main workspace AGENTS.md contains Home Archive routing directives
==========================================
All Home Archive integration checks passed.
OpenClaw Home Archive integration is complete and verified.
```

*(Note: If optional hardening settings in Part 3 are not enabled, they will be reported as `[INFO]` and will not prevent `./install.sh --check` from passing.)*

---

<a name="uninstall"></a>
## Uninstalling OpenClaw Integration

To decommission Home Archive:

1. **Remove Software Artifacts**:
   ```bash
   ./install.sh --uninstall
   ```
   *Removes `~/.openclaw/workspace/skills/home-archive` and `~/.openclaw/workspaces/home-archive`. **Never** touches or deletes your archive records at `~/Documents/OpenClaw/HomeArchive` or Apple Photos assets.*

2. **Remove Dedicated Agent & Skill Config**:
   ```bash
   openclaw config unset agents.entries.home-archive
   openclaw config unset skills.entries.home-archive
   ```

3. **Remove from Main Agent Delegation**:
   Inspect `openclaw config get agents.entries.main.subagents.allowAgents`. Remove `"home-archive"` from that array and update it with `openclaw config set`. If it was the only allowed subagent:
   ```bash
   openclaw config set agents.entries.main.subagents.allowAgents '[]' --strict-json
   ```

4. **Remove Routing Directives from Main `AGENTS.md`**:
   Open `~/.openclaw/workspace/AGENTS.md` and delete the block between:
   ```markdown
   <!-- BEGIN OPENCLAW HOME ARCHIVE MANAGED ROUTING DIRECTIVES -->
   ...
   <!-- END OPENCLAW HOME ARCHIVE MANAGED ROUTING DIRECTIVES -->
   ```

5. **Restart Gateway**:
   ```bash
   openclaw gateway restart
   ```

Your archive data at `~/Documents/OpenClaw/HomeArchive` remains completely intact and accessible via direct CLI commands (`python3 scripts/home_archive.py`).
