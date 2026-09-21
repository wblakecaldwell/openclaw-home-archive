# Main Agent Directives: Personal Archive Routing & Relay

Add the following instructions to the `main` agent's directives file (e.g. `~/.openclaw/workspace/AGENTS.md`):

```markdown
<!-- BEGIN OPENCLAW PERSONAL ARCHIVE MANAGED ROUTING DIRECTIVES -->
## Personal Archive Intent & Delegation

When the user asks to save, update, search, view, or delete durable personal records and evidence (purchases, receipts, warranties, manuals, equipment, vehicle or bicycle records, contractors, repairs, business cards, documents, correspondence, projects, measurements, photos, belongings):

### 1. Intent Recognition & Delegation
- Recognize Personal Archive intent from user requests regarding durable records or evidence preservation and retrieval (e.g., "Save this to my Personal Archive", "Archive this", "Save this receipt in my archive", "What does my archive say about my bike?", "Find the business card I archived", "Add this photo to the car record", "Delete that receipt from my archive").
- Always delegate to the dedicated agent via `sessions_spawn`.
- You MUST specify:
  - `agentId`: `"archivist"`
  - `context`: `"isolated"` (MANDATORY: NEVER use `"fork"`)
  - `taskName`: `"personal-archive-task"`

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

- **To update later**: Replace the content between the `<!-- BEGIN ... -->` and `<!-- END ... -->` markers.
- **To remove later**: Delete the entire block including both comment markers.
