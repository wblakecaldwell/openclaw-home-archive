---
name: personal-archive
description: Save, update, find, and return durable, evidence-backed personal records and attachments such as purchases, receipts, warranties, manuals, equipment, vehicles, bicycles, contractors, repairs, business cards, documents, correspondence, projects, measurements, photos, and belongings.
metadata:
  openclaw:
    requires:
      bins: [python3]
---
# Personal Archive

Authoritative root: `<archive-root>`, the configured personal archive directory outside this repository. Set `PERSONAL_ARCHIVE_ROOT` in the environment used to run the CLI, including commands launched by OpenClaw. `<archive-root>` is a documentation placeholder; replace it with the chosen absolute path (e.g. `~/Documents/OpenClaw/PersonalArchive`). Apple Photos is a rebuildable projection only.

Persist the location in OpenClaw configuration under
`skills.entries.personal-archive.env.PERSONAL_ARCHIVE_ROOT` (the installer handles setup).
If configuration is missing, complete setup before attempting archive operations;
never invent a location. Direct terminal and sandboxed invocations must receive
the environment variable explicitly.

## Execution Role & Boundary
This skill is executed by the dedicated `archivist` agent in an isolated subagent context (`context: "isolated"`). The main conversational agent routes personal archive requests here and resolves conversation-dependent references (e.g. "it" -> "the bike").

Domain interpretation belongs here in `archivist`:
- Normalize relative dates ("today", "yesterday", "last week") against the invocation timestamp provided in the task into structured ISO calendar dates (`YYYY-MM-DD`). Preserve original user wording in notes/events.
- Extract durable facts from user text and attachments.
- Assign provenance (`source=user` or attachment basename) and confidence.

## Rule
Never manually mutate archive files. Use `python3 {baseDir}/scripts/personal_archive.py ...`. The CLI owns IDs, atomic writes, hashes, event history, dedupe, soft deletion, merges, and Photos reconciliation. Never fabricate `ARCHIVE-...` or `ARCHIVE-ATTACH-...` identifiers. Every mutation requires parsing CLI JSON output and verifying `ok: true`.

## Ingest
Inspect all supplied attachments. Extract useful durable facts only (brand/model/serial, people/business/contact info, dates, warranty, parts, dimensions, price, invoice/receipt IDs). Every fact needs provenance: `source=user` for explicit user statements or the attachment basename for extracted facts. Prefer omission to guessing. Search before adding when the message may refer to an existing entity.

Create with a temporary JSON spec: `python3 {baseDir}/scripts/personal_archive.py create --spec /tmp/spec.json`. Add later evidence with `... add ARCHIVE-... --spec /tmp/spec.json`. Spec fields: `title`, `summary`, `user_text`, optional `event_date`, `facts` array (`key`,`value`,`source`,`confidence`), `attachments` array (`path`,`role`,`description`, optional `publish_to_photos`), and `keywords`. Image attachments publish to Photos by default.

Corrections: `... set-fact ARCHIVE-... --key KEY --value VALUE --source user --confidence high`. Remove fact: `... remove-fact ARCHIVE-... --key KEY`. Remove attachment: `... remove-attachment ARCHIVE-ATTACH-...`. Soft-delete record: `... delete ARCHIVE-...`. Merge duplicates: `... merge ARCHIVE-CANONICAL ARCHIVE-DUPLICATE`. Reversible operations need no confirmation; report what changed. Never permanently purge originals without explicit confirmation immediately before destruction.

## Recall
Search: `... search "query" --limit 10`. Show record: `... show ARCHIVE-...`. Resolve original attachment: `... get-attachment ARCHIVE-ATTACH-...`. When asked to show/send an artifact, return the actual original through the channel media/file mechanism, not just a description.

## Photos
Regular album name: `Personal Archive`. Metadata is generated from archive state and includes title, caption, useful keywords, entity ID, and attachment ID. Normal reconcile: `... photos-sync`; preview with `--dry-run`. Disaster rebuild preview: `... photos-rebuild --dry-run`. Real rebuild requires explicit confirmation, then `... photos-rebuild --confirm`. The Photos deletion code may only touch assets carrying an `ARCHIVE-ATTACH-...` keyword. Photos failure must never roll back authoritative archive ingestion.

## Response Contract
Your final response to the parent agent MUST include a standard JSON response envelope enclosed in a ```json code block:
```json
{
  "ok": true,
  "source": "personal-archive",
  "operation": "search",
  "status": "found",
  "record_id": "ARCHIVE-20260920-0001",
  "relay_message": "The toaster is a Breville model BTA820XL (Archive ID: ARCHIVE-20260920-0001).",
  "facts": { "brand": "Breville", "model": "BTA820XL" },
  "evidence": [
    { "attachment_id": "ARCHIVE-ATTACH-20260920-0001", "fact": "model", "value": "BTA820XL", "source": "receipt.pdf" }
  ]
}
```
Status codes: `"found"` (fact/record found), `"not_found"` (searched, no record/fact in archive), `"mutated"` (created/updated/merged), `"error"` (CLI error).
`relay_message` must be a self-contained, user-facing statement ready to be relayed directly to the user without alteration.

## Maintenance
`... doctor`.
