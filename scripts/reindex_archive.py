#!/usr/bin/env python3
"""OpenClaw Personal Archive - Admin Database Reindexer.

Scans the archive records directory, inspects stored evidence image attachments,
and runs local Gemma 4 multimodal vision to extract facts, contact info, model numbers,
and search keywords into metadata.json and record.md.

Adheres to Personal Archive invariants:
- User-provided facts ('source: user') are NEVER overwritten.
- Facts are stored with provenance ('source: <filename>', 'confidence: high').
- Fact updates supersede prior values while preserving history.
- Idempotent: running repeatedly on already-enriched records is a clean no-op.
- Supports --dry-run to preview extractions without modifying disk state.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional

# Ensure scripts directory is on sys.path
_scripts_dir = Path(__file__).resolve().parent
if str(_scripts_dir) not in sys.path:
    sys.path.insert(0, str(_scripts_dir))

import mcp_server  # noqa: E402
import personal_archive  # noqa: E402


def reindex_record(
    record_id: str,
    dry_run: bool = False,
    force: bool = False,
    timeout: int = 60,
    verbose: bool = True,
) -> Dict[str, Any]:
    """Reindex a single archive record by analyzing its image attachments with Gemma 4 vision."""
    personal_archive.configure_root()
    m = personal_archive.load(record_id)

    if m.get("deleted", False):
        return {"id": record_id, "status": "skipped", "reason": "record_deleted"}

    active_attachments = [a for a in m.get("attachments", []) if a.get("active", True)]
    image_attachments = []
    for a in active_attachments:
        rel = a.get("stored_relpath", "")
        ext = Path(rel).suffix.lower()
        mime = a.get("mime", "")
        if ext in personal_archive.IMAGE_EXTS or mime.startswith("image/"):
            image_attachments.append(a)

    if not image_attachments:
        return {"id": record_id, "status": "skipped", "reason": "no_image_attachments"}

    rec_dir = personal_archive.rdir(record_id)
    active_facts = {
        str(f.get("key", "")).strip().lower(): f
        for f in m.get("facts", [])
        if f.get("active", True) and "key" in f
    }

    facts_added: List[Dict[str, Any]] = []
    facts_superseded: List[Dict[str, Any]] = []
    keywords_added: List[str] = []
    title_updated = False
    summary_updated = False
    attachment_errors: List[Dict[str, str]] = []

    for att in image_attachments:
        stored_rel = att.get("stored_relpath")
        if not stored_rel:
            continue
        att_path = rec_dir / stored_rel
        if not att_path.is_file():
            attachment_errors.append(
                {"attachment": att.get("filename", ""), "error": f"File not found on disk: {att_path}"}
            )
            continue

        data_uri, source_name = mcp_server.prepare_image_data_uri(str(att_path), None)
        if not data_uri:
            continue

        if verbose:
            print(f"[{record_id}] Analyzing image: {att.get('filename')} ...")

        # Construct contextual prompt
        prompt_parts = [
            "Analyze this evidence image thoroughly for durable personal record keeping.",
            "Extract all legible text and structured facts (business/contractor names, contact info "
            "like phone/email/address, brand, model, serial number, dates, amounts, etc.) and suggested search keywords.",
            "Respond with ONLY a JSON object with keys 'title', 'summary', 'facts' (list of {key, value}), and 'keywords' (list of strings).",
        ]
        context_items = []
        if m.get("title") and m["title"] != record_id:
            context_items.append(f"Title: {m['title']}")
        if m.get("summary"):
            context_items.append(f"Summary: {m['summary']}")
        if att.get("description"):
            context_items.append(f"Description: {att['description']}")
        if context_items:
            prompt_parts.append("Context: " + " | ".join(context_items))

        prompt_text = "\n".join(prompt_parts)

        try:
            raw_analysis = mcp_server.query_vision_model(data_uri, prompt_text, timeout=timeout)
            extracted = mcp_server.parse_structured_extraction(raw_analysis)
        except Exception as exc:
            err_msg = str(exc)
            attachment_errors.append({"attachment": att.get("filename", ""), "error": err_msg})
            if verbose:
                print(f"  [error] Vision extraction failed for {att.get('filename')}: {err_msg}", file=sys.stderr)
            continue

        # 1. Title enrichment (only if missing or generic ID)
        if (not m.get("title") or m["title"] == record_id) and extracted.get("title"):
            m["title"] = extracted["title"]
            title_updated = True
            if verbose:
                print(f"  + Title updated: {m['title']}")

        # 2. Summary enrichment (only if missing)
        if not m.get("summary") and extracted.get("summary"):
            m["summary"] = extracted["summary"]
            summary_updated = True
            if verbose:
                print(f"  + Summary updated: {m['summary']}")

        # 3. Facts merging
        for ef in extracted.get("facts", []):
            k = str(ef.get("key", "")).strip()
            v = str(ef.get("value", "")).strip()
            if not k or not v:
                continue
            k_lower = k.lower()
            existing = active_facts.get(k_lower)

            if existing is None:
                # Discovered a brand new fact
                new_fact = {
                    "key": k,
                    "value": v,
                    "source": att.get("filename", source_name or "image"),
                    "confidence": "high",
                }
                personal_archive.add_fact(m, new_fact)
                active_facts[k_lower] = new_fact
                facts_added.append(new_fact)
                if verbose:
                    print(f"  + Discovered fact: {k} = {v} (source: {new_fact['source']})")
            else:
                existing_val = str(existing.get("value", "")).strip()
                if existing_val.lower() == v.lower():
                    # Identical value: clean no-op
                    continue

                # Conflicting value
                if existing.get("source") == "user":
                    # Human/user input is always authoritative over automated vision
                    if verbose:
                        print(
                            f"  [skip] Preserving user-stated fact '{k}' = '{existing_val}' "
                            f"(ignoring vision extracted '{v}')"
                        )
                elif force:
                    # Automated fact, --force allows supersession with history
                    new_fact = {
                        "key": k,
                        "value": v,
                        "source": att.get("filename", source_name or "image"),
                        "confidence": "high",
                    }
                    personal_archive.add_fact(m, new_fact)
                    active_facts[k_lower] = new_fact
                    facts_superseded.append({"key": k, "old_value": existing_val, "new_value": v})
                    if verbose:
                        print(f"  * Superseded automated fact: {k} = '{v}' (was: '{existing_val}')")
                else:
                    if verbose:
                        print(
                            f"  [skip] Existing automated fact '{k}' = '{existing_val}' "
                            f"(use --force to supersede with '{v}')"
                        )

        # 4. Search keywords merging
        existing_keywords_lower = {str(kw).strip().lower() for kw in m.get("keywords", [])}
        for kw in extracted.get("keywords", []):
            kws = str(kw).strip()
            if kws and kws.lower() not in existing_keywords_lower:
                m.setdefault("keywords", []).append(kws)
                existing_keywords_lower.add(kws.lower())
                keywords_added.append(kws)
                if verbose:
                    print(f"  + Added keyword: {kws}")

    has_changes = bool(facts_added or facts_superseded or keywords_added or title_updated or summary_updated)

    if not has_changes:
        return {
            "id": record_id,
            "status": "unchanged",
            "reason": "up_to_date",
            "attachment_errors": attachment_errors,
        }

    if not dry_run:
        now_ts = personal_archive.now()
        m["updated_at"] = now_ts
        personal_archive.save(m)
        event_record = {
            "at": now_ts,
            "type": "reindex",
            "facts_added": facts_added,
            "facts_superseded": facts_superseded,
            "keywords_added": keywords_added,
            "title_updated": title_updated,
            "summary_updated": summary_updated,
        }
        personal_archive.append_jsonl(rec_dir / "events.jsonl", event_record)

    return {
        "id": record_id,
        "status": "updated",
        "dry_run": dry_run,
        "facts_added": facts_added,
        "facts_superseded": facts_superseded,
        "keywords_added": keywords_added,
        "title_updated": title_updated,
        "summary_updated": summary_updated,
        "attachment_errors": attachment_errors,
    }


def reindex_all(
    root: Optional[str] = None,
    record_id: Optional[str] = None,
    dry_run: bool = False,
    force: bool = False,
    timeout: int = 60,
    verbose: bool = True,
) -> Dict[str, Any]:
    """Reindex all records or a selected record across the archive."""
    if root:
        os.environ["PERSONAL_ARCHIVE_ROOT"] = str(Path(root).expanduser().resolve())
    personal_archive.configure_root()
    personal_archive.init()

    if record_id:
        record_ids = [record_id.strip()]
    else:
        record_ids = sorted(
            [
                d.name
                for d in personal_archive.RECORDS.glob("ARCHIVE-*")
                if d.is_dir() and personal_archive.RECORD_ID_RE.match(d.name)
            ]
        )

    results: List[Dict[str, Any]] = []
    total_facts_added = 0
    total_facts_superseded = 0
    total_keywords_added = 0
    updated_count = 0
    skipped_count = 0
    unchanged_count = 0

    if verbose:
        mode_str = " (DRY RUN)" if dry_run else ""
        print(f"=== Personal Archive Reindexer{mode_str} ===")
        print(f"Archive Root: {personal_archive.ROOT}")
        print(f"Scanning {len(record_ids)} record(s)...\n")

    for rid in record_ids:
        try:
            res = reindex_record(
                rid,
                dry_run=dry_run,
                force=force,
                timeout=timeout,
                verbose=verbose,
            )
            results.append(res)
            st = res.get("status")
            if st == "updated":
                updated_count += 1
                total_facts_added += len(res.get("facts_added", []))
                total_facts_superseded += len(res.get("facts_superseded", []))
                total_keywords_added += len(res.get("keywords_added", []))
            elif st == "skipped":
                skipped_count += 1
            elif st == "unchanged":
                unchanged_count += 1
        except Exception as exc:
            err_res = {"id": rid, "status": "error", "error": str(exc)}
            results.append(err_res)
            if verbose:
                print(f"[{rid}] Error during reindex: {exc}", file=sys.stderr)

    summary = {
        "ok": True,
        "root": str(personal_archive.ROOT),
        "dry_run": dry_run,
        "total_scanned": len(record_ids),
        "records_updated": updated_count,
        "records_unchanged": unchanged_count,
        "records_skipped": skipped_count,
        "total_facts_added": total_facts_added,
        "total_facts_superseded": total_facts_superseded,
        "total_keywords_added": total_keywords_added,
        "results": results,
    }

    if verbose:
        print("\n=== Reindexing Summary ===")
        print(f"Total Records Scanned: {len(record_ids)}")
        print(f"Records Updated:       {updated_count}{' (simulated)' if dry_run else ''}")
        print(f"Records Unchanged:     {unchanged_count}")
        print(f"Records Skipped:       {skipped_count}")
        print(f"New Facts Added:       {total_facts_added}")
        print(f"Facts Superseded:      {total_facts_superseded}")
        print(f"New Keywords Added:    {total_keywords_added}")

    return summary


def main():
    parser = argparse.ArgumentParser(
        description="Reindex Personal Archive records with local Gemma 4 vision model."
    )
    parser.add_argument(
        "--root",
        help="Path to archive root (defaults to PERSONAL_ARCHIVE_ROOT or ~/Documents/OpenClaw/PersonalArchive)",
    )
    parser.add_argument(
        "-r",
        "--record",
        help="Reindex a specific record ID instead of the entire archive (e.g. ARCHIVE-20260920-0001)",
    )
    parser.add_argument(
        "-n",
        "--dry-run",
        action="store_true",
        help="Simulate reindexing without writing any changes to disk",
    )
    parser.add_argument(
        "-f",
        "--force",
        action="store_true",
        help="Allow vision model to supersede existing automated facts (user facts are always preserved)",
    )
    parser.add_argument(
        "-t",
        "--timeout",
        type=int,
        default=60,
        help="Timeout in seconds for vision model requests (default: 60)",
    )
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Suppress detailed progress logs and only output summary",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output the final summary as a JSON object",
    )

    args = parser.parse_args()

    summary = reindex_all(
        root=args.root,
        record_id=args.record,
        dry_run=args.dry_run,
        force=args.force,
        timeout=args.timeout,
        verbose=not args.quiet and not args.json,
    )

    if args.json:
        print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
