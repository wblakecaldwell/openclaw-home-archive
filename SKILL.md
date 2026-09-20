---
name: home-archive
description: Save, update, find, and return durable household records and attachments such as appliances, vehicles, contractors, repairs, receipts, manuals, and home projects.
metadata:
  openclaw:
    requires:
      bins: [python3]
---
# Home Archive

Authoritative root: `<archive-root>`, the configured household archive directory outside this repository. Set `HOME_ARCHIVE_ROOT` in the environment used to run the CLI, including commands launched by OpenClaw. `<archive-root>` is a documentation placeholder; replace it with the chosen absolute path. Apple Photos is a rebuildable projection only.

## When to use
Archive when intent is reasonably clear (for example “here’s the toaster we just bought”, “save this”, “this is the deck guy”, “add this receipt”). If archive intent or target record is ambiguous, ask. Never require categories.

## Rule
Never manually mutate archive files. Use `python3 {baseDir}/scripts/home_archive.py ...`. The CLI owns IDs, atomic writes, hashes, event history, dedupe, soft deletion, merges, and Photos reconciliation.

## Ingest
Inspect all supplied attachments. Extract useful durable facts only (brand/model/serial, people/business/contact info, dates, warranty, parts, dimensions, paint, price, invoice/receipt IDs). Every fact needs provenance: `source=user` for explicit user statements or the attachment basename for extracted facts. Prefer omission to guessing. Search before adding when the message may refer to an existing entity.

Create with a temporary JSON spec: `python3 {baseDir}/scripts/home_archive.py create --spec /tmp/spec.json`. Add later evidence with `... add HA-... --spec /tmp/spec.json`. Spec fields: `title`, `summary`, `user_text`, optional `event_date`, `facts` array (`key`,`value`,`source`,`confidence`), `attachments` array (`path`,`role`,`description`, optional `publish_to_photos`), and `keywords`. Image attachments publish to Photos by default.

Corrections: `... set-fact HA-... --key KEY --value VALUE --source user --confidence high`. Remove fact: `... remove-fact HA-... --key KEY`. Remove attachment: `... remove-attachment HAA-...`. Soft-delete record: `... delete HA-...`. Merge duplicates: `... merge HA-CANONICAL HA-DUPLICATE`. Reversible operations need no confirmation; report what changed. Never permanently purge originals without explicit confirmation immediately before destruction.

## Recall
Search: `... search "query" --limit 10`. Show record: `... show HA-...`. Resolve original attachment: `... get-attachment HAA-...`. When asked to show/send an artifact, return the actual original through the channel media/file mechanism, not just a description.

## Photos
Regular album name: `Home Archive`. Metadata is generated from archive state and includes title, caption, useful keywords, entity ID, and attachment ID. Normal reconcile: `... photos-sync`; preview with `--dry-run`. Disaster rebuild preview: `... photos-rebuild --dry-run`. Real rebuild requires explicit confirmation, then `... photos-rebuild --confirm`. The Photos deletion code may only touch assets carrying an `HAA-...` keyword. Photos failure must never roll back authoritative archive ingestion.

Maintenance: `... doctor`.
