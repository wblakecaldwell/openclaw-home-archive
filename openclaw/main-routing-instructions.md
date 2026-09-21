# Main Agent Directives: Home Archive Routing & Relay

Add the following instructions to the `main` agent's directives file (e.g. `~/.openclaw/workspace/AGENTS.md`):

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
