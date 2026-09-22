#!/usr/bin/env python3
"""OpenClaw Personal Archive - Model Context Protocol (MCP) Stdio Server.

Implements JSON-RPC 2.0 stdio transport adhering to the MCP 2024-11-05 specification.
Exposes native archive tools directly to OpenClaw agents without requiring shell exec.
"""

from __future__ import annotations

import base64
import json
import mimetypes
import os
from pathlib import Path
import re
import sys
from typing import Any, Dict, Optional, Tuple
import urllib.error
import urllib.request

# Ensure personal_archive module is importable from the same directory
_scripts_dir = Path(__file__).resolve().parent
if str(_scripts_dir) not in sys.path:
    sys.path.insert(0, str(_scripts_dir))

import personal_archive  # noqa: E402

PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "personal-archive"
SERVER_VERSION = "0.2.0"

TOOLS = [
    {
        "name": "archive_create",
        "description": (
            "Create a new durable personal archive entity with facts, notes, and evidence attachments. "
            "Atomically allocates an authoritative ARCHIVE-YYYYMMDD-NNNN identifier. "
            "If image attachments (e.g. receipts, business cards, equipment tags, photos) are provided, "
            "local Gemma 4 multimodal vision automatically inspects them to extract facts, contact details, "
            "model numbers, and search keywords."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "Human-readable title describing the entity (e.g. 'Breville Toaster', 'Water Heater Receipt').",
                },
                "summary": {
                    "type": "string",
                    "description": "Brief summary of the entity and context.",
                },
                "event_date": {
                    "type": "string",
                    "description": "ISO date (YYYY-MM-DD) when the event occurred (e.g. purchase or installation date).",
                },
                "user_text": {
                    "type": "string",
                    "description": "Verbatim statement or request from the user preserving their original phrasing.",
                },
                "keywords": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Keywords or search tags (e.g. ['kitchen', 'appliance']).",
                },
                "facts": {
                    "description": (
                        "Structured facts extracted from the conversation or evidence. "
                        "Can be a list of objects ({key, value, source, confidence}) or a key-value dictionary."
                    ),
                    "oneOf": [
                        {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "key": {"type": "string"},
                                    "value": {"type": "string"},
                                    "source": {"type": "string"},
                                    "confidence": {"type": "string"},
                                },
                                "required": ["key", "value"],
                            },
                        },
                        {"type": "object"},
                    ],
                },
                "attachments": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "path": {
                                "type": "string",
                                "description": "Absolute path or URI of the evidence file (e.g. /path/to/img.jpg or media://inbound/...).",
                            },
                            "role": {
                                "type": "string",
                                "description": "Role of the attachment (e.g. 'receipt', 'photo', 'serial_number_plate', 'business_card', 'manual').",
                            },
                            "description": {
                                "type": "string",
                                "description": "Detailed description of what this evidence image or document shows.",
                            },
                        },
                        "required": ["path"],
                    },
                    "description": "List of evidence files to copy and preserve in the archive.",
                },
            },
            "required": ["title"],
        },
    },
    {
        "name": "archive_search",
        "description": (
            "Search existing non-deleted archive records by keywords, titles, summaries, facts, and attachment metadata. "
            "Returns ranked matches with IDs and relevant facts."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search terms to find relevant records (e.g. 'toaster', 'water heater', 'Joe deck').",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of results to return (default: 10).",
                    "default": 10,
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "archive_show",
        "description": (
            "Inspect full metadata, structured facts, chronological notes, and attachments for a specific archive entity."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "id": {
                    "type": "string",
                    "description": "Authoritative entity ID (e.g. 'ARCHIVE-20260920-0001').",
                }
            },
            "required": ["id"],
        },
    },
    {
        "name": "archive_add_evidence",
        "description": (
            "Add additional evidence attachments, notes, keywords, or facts to an existing archive entity. "
            "Image attachments are automatically analyzed by local Gemma 4 vision to extract facts and search "
            "keywords without overwriting previous evidence. Appends to event history."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "id": {
                    "type": "string",
                    "description": "Authoritative entity ID (e.g. 'ARCHIVE-20260920-0001').",
                },
                "title": {
                    "type": "string",
                    "description": "Updated title (optional).",
                },
                "summary": {
                    "type": "string",
                    "description": "Updated summary (optional).",
                },
                "event_date": {
                    "type": "string",
                    "description": "Updated ISO event date (optional).",
                },
                "user_text": {
                    "type": "string",
                    "description": "New user statement or note to append to history.",
                },
                "keywords": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Additional keywords to merge.",
                },
                "facts": {
                    "description": "Structured facts to add or update.",
                    "oneOf": [
                        {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "key": {"type": "string"},
                                    "value": {"type": "string"},
                                    "source": {"type": "string"},
                                    "confidence": {"type": "string"},
                                },
                                "required": ["key", "value"],
                            },
                        },
                        {"type": "object"},
                    ],
                },
                "attachments": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "path": {
                                "type": "string",
                                "description": "Absolute path or URI of the evidence file to preserve.",
                            },
                            "role": {
                                "type": "string",
                                "description": "Role of the attachment.",
                            },
                            "description": {
                                "type": "string",
                                "description": "Description of what this evidence shows.",
                            },
                        },
                        "required": ["path"],
                    },
                    "description": "Evidence attachments to copy and preserve.",
                },
            },
            "required": ["id"],
        },
    },
    {
        "name": "archive_set_fact",
        "description": (
            "Set or update a single structured fact with provenance tracking on an existing archive entity."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "id": {
                    "type": "string",
                    "description": "Authoritative entity ID (e.g. 'ARCHIVE-20260920-0001').",
                },
                "key": {
                    "type": "string",
                    "description": "Fact key (e.g. 'model', 'serial_number', 'filter_size', 'contractor_phone').",
                },
                "value": {
                    "type": "string",
                    "description": "Fact value (e.g. 'BTA820XL', '16x25x1').",
                },
                "source": {
                    "type": "string",
                    "description": "Origin of the fact (e.g. 'user', 'IMG_1036.jpg', 'receipt.pdf').",
                    "default": "user",
                },
                "confidence": {
                    "type": "string",
                    "description": "Confidence level ('high', 'medium', 'low').",
                    "default": "high",
                },
            },
            "required": ["id", "key", "value"],
        },
    },
    {
        "name": "archive_get_attachment",
        "description": (
            "Lookup an attachment by its durable attachment ID (ARCHIVE-ATTACH-YYYYMMDD-NNNN) "
            "and retrieve its metadata and stored filesystem path."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "id": {
                    "type": "string",
                    "description": "Authoritative attachment ID (e.g. 'ARCHIVE-ATTACH-20260920-0001').",
                }
            },
            "required": ["id"],
        },
    },
    {
        "name": "archive_delete",
        "description": (
            "Soft-delete an archive entity. Marks it deleted and excludes it from normal search "
            "while preserving durable evidence files."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "id": {
                    "type": "string",
                    "description": "Authoritative entity ID to delete (e.g. 'ARCHIVE-20260920-0001').",
                }
            },
            "required": ["id"],
        },
    },
    {
        "name": "archive_doctor",
        "description": (
            "Run diagnostic checks on the archive: validates root directory, cleans staging, "
            "verifies attachment hashes, detects skeletal records, and reports Photos integration status."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "archive_inspect_image",
        "description": (
            "Inspect an evidence image file (receipt, business card, equipment plate, document) "
            "using local multimodal vision (Gemma 4 via LM Studio). Reads the image, queries "
            "the local vision model, and returns extracted text, contractor/vendor info, contact "
            "details, model/serial numbers, and suggested search keywords."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Filesystem path to the image file (or base64 data URI).",
                },
                "image_base64": {
                    "type": "string",
                    "description": "Optional raw base64-encoded image string if path is not provided.",
                },
                "context": {
                    "type": "string",
                    "description": (
                        "Optional context or guidance (e.g. 'Extract contact details from this business card' "
                        "or 'Find model and serial number')."
                    ),
                },
            },
        },
    },
]


def ensure_archive_configured():
    """Ensure personal_archive has resolved its root from PERSONAL_ARCHIVE_ROOT."""
    if personal_archive.ROOT is None:
        personal_archive.configure_root()


def prepare_image_data_uri(
    raw_path: Optional[str],
    base64_data: Optional[str],
) -> Tuple[Optional[str], Optional[str]]:
    """Convert an image file path or raw base64 string into a data URI.

    Returns (data_uri, source_name).
    """
    if base64_data:
        b64 = base64_data.strip()
        if b64.startswith("data:image/"):
            return b64, "image_base64"
        return f"data:image/jpeg;base64,{b64}", "image_base64"

    if not raw_path:
        return None, None

    raw_str = str(raw_path).strip()
    if raw_str.startswith("data:image/"):
        return raw_str, "data_uri"

    try:
        p = personal_archive.resolve_attachment_path(raw_str)
        if not p.is_file():
            return None, None
        mime, _ = mimetypes.guess_type(str(p))
        mime_type = mime if (mime and mime.startswith("image/")) else "image/jpeg"
        raw_bytes = p.read_bytes()
        encoded = base64.b64encode(raw_bytes).decode("ascii")
        return f"data:{mime_type};base64,{encoded}", p.name
    except Exception:
        return None, None


def query_vision_model(
    data_uri: str,
    prompt_text: str,
    timeout: int = 30,
) -> str:
    """Query the local vision model (Gemma 4 via LM Studio) with an image data URI and prompt."""
    raw_url = os.environ.get("LMSTUDIO_URL") or os.environ.get("LM_STUDIO_URL") or "http://localhost:1234/v1"
    raw_url = raw_url.rstrip("/")
    if not raw_url.endswith("/chat/completions"):
        endpoint_url = f"{raw_url}/chat/completions"
    else:
        endpoint_url = raw_url

    model_name = os.environ.get("PERSONAL_ARCHIVIST_MODEL") or os.environ.get("LMSTUDIO_MODEL") or os.environ.get("LM_STUDIO_MODEL") or "google/gemma-4-e4b"

    req_payload = {
        "model": model_name,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt_text},
                    {"type": "image_url", "image_url": {"url": data_uri}},
                ],
            }
        ],
        "temperature": 0.1,
    }

    headers = {"Content-Type": "application/json"}
    api_token = (
        os.environ.get("PERSONAL_ARCHIVIST_LMSTUDIO_API_TOKEN")
        or os.environ.get("LMSTUDIO_API_TOKEN")
        or os.environ.get("LM_API_TOKEN")
        or os.environ.get("LMSTUDIO_API_KEY")
    )
    if api_token:
        headers["Authorization"] = f"Bearer {api_token.strip()}"

    req_data = json.dumps(req_payload).encode("utf-8")
    req = urllib.request.Request(
        endpoint_url,
        data=req_data,
        headers=headers,
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            resp_body = resp.read().decode("utf-8")
            data = json.loads(resp_body)
            return data["choices"][0]["message"]["content"]
    except urllib.error.HTTPError as exc:
        err_msg = ""
        try:
            err_msg = exc.read().decode("utf-8")
        except Exception:
            pass
        if exc.code == 401:
            raise RuntimeError(
                f"LM Studio authentication failed (HTTP 401): {err_msg or exc}. "
                "Either disable 'Require Authentication' in LM Studio Developer tab -> Local Server, "
                "or set the PERSONAL_ARCHIVIST_LMSTUDIO_API_TOKEN or LMSTUDIO_API_TOKEN environment variable with a valid token."
            ) from exc
        raise RuntimeError(f"Vision model request failed (HTTP {exc.code}): {err_msg or exc}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(
            f"Failed to connect to local vision model server at {endpoint_url}: {exc}. "
            "Ensure LM Studio is running with local server enabled."
        ) from exc
    except Exception as exc:
        raise RuntimeError(f"Vision model extraction failed: {exc}") from exc


def parse_structured_extraction(raw_text: str) -> Dict[str, Any]:
    """Parse structured facts and keywords from vision model text output.

    Handles:
    - Raw JSON
    - Markdown fenced JSON blocks (```json ... ```)
    - Substrings containing JSON objects
    - Freeform text with key-value lines (e.g. Phone: ..., Extracted Text: ..., Keywords: ...)
    """
    text = (raw_text or "").strip()
    result: Dict[str, Any] = {
        "title": None,
        "summary": None,
        "facts": [],
        "keywords": [],
    }

    if not text:
        return result

    parsed_obj = None

    # 1. Try direct JSON parse
    try:
        cand = json.loads(text)
        if isinstance(cand, dict):
            parsed_obj = cand
    except Exception:
        pass

    # 2. Try markdown fenced code block
    if parsed_obj is None:
        fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        if fence_match:
            try:
                cand = json.loads(fence_match.group(1))
                if isinstance(cand, dict):
                    parsed_obj = cand
            except Exception:
                pass

    # 3. Try finding outermost { ... }
    if parsed_obj is None:
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end > start:
            try:
                cand = json.loads(text[start : end + 1])
                if isinstance(cand, dict):
                    parsed_obj = cand
            except Exception:
                pass

    if isinstance(parsed_obj, dict):
        if parsed_obj.get("title") and isinstance(parsed_obj["title"], str):
            result["title"] = parsed_obj["title"].strip()
        if parsed_obj.get("summary") and isinstance(parsed_obj["summary"], str):
            result["summary"] = parsed_obj["summary"].strip()

        # Extract facts
        facts_raw = parsed_obj.get("facts")
        if isinstance(facts_raw, list):
            for item in facts_raw:
                if isinstance(item, dict) and "key" in item and "value" in item:
                    k = str(item["key"]).strip()
                    v = str(item["value"]).strip()
                    if k and v:
                        result["facts"].append({"key": k, "value": v})
        elif isinstance(facts_raw, dict):
            for k, v in facts_raw.items():
                k_str = str(k).strip()
                v_str = str(v).strip()
                if k_str and v_str:
                    result["facts"].append({"key": k_str, "value": v_str})

        # Extract keywords
        kw_raw = parsed_obj.get("keywords")
        if isinstance(kw_raw, list):
            for item in kw_raw:
                s = str(item).strip()
                if s:
                    result["keywords"].append(s)
        elif isinstance(kw_raw, str):
            for item in kw_raw.split(","):
                s = item.strip()
                if s:
                    result["keywords"].append(s)

        return result

    # 4. Fallback: Parse key-value lines and keywords from freeform text
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for line in lines:
        if line.lower().startswith("keywords:"):
            kw_part = line.split(":", 1)[1]
            for item in kw_part.split(","):
                s = item.strip().strip("-*• ")
                if s:
                    result["keywords"].append(s)
            continue

        if line.lower().startswith("title:"):
            result["title"] = line.split(":", 1)[1].strip()
            continue

        if line.lower().startswith("summary:"):
            result["summary"] = line.split(":", 1)[1].strip()
            continue

        if ":" in line and not line.startswith("http") and not line.startswith("//"):
            k_part, v_part = line.split(":", 1)
            k_clean = k_part.strip().lstrip("-*• ").strip()
            v_clean = v_part.strip()
            if 1 <= len(k_clean) <= 35 and len(v_clean) > 0 and not k_clean.startswith("#"):
                norm_key = re.sub(r"\s+", "_", k_clean).lower()
                if norm_key not in ("extracted_text", "key_facts", "analysis", "note"):
                    result["facts"].append({"key": norm_key, "value": v_clean})

    return result


def enrich_spec_with_image_analysis(arguments: Dict[str, Any]) -> None:
    """Enrich an archive operation spec in-place with vision-extracted facts and keywords.

    If image attachments are present, local Gemma 4 is queried to extract structured
    facts (contact info, model numbers, etc.) and search keywords.
    Any user-provided facts and titles take precedence over extracted ones.
    If the vision model is unreachable or fails, execution continues gracefully without error.
    """
    if os.environ.get("PERSONAL_ARCHIVE_AUTO_EXTRACT", "1").lower() in ("0", "false", "no"):
        return
    if arguments.get("auto_extract") is False:
        return

    attachments = arguments.get("attachments")
    if not attachments or not isinstance(attachments, list):
        return

    for att in attachments:
        if not isinstance(att, dict):
            continue
        raw_path = att.get("path")
        base64_data = att.get("image_base64")
        if not raw_path and not base64_data:
            continue

        # Check if attachment is an image
        is_image = False
        if base64_data:
            is_image = True
        elif raw_path:
            raw_str = str(raw_path).strip()
            if raw_str.startswith("data:image/"):
                is_image = True
            else:
                ext = Path(raw_str).suffix.lower()
                mime, _ = mimetypes.guess_type(raw_str)
                if ext in personal_archive.IMAGE_EXTS or (mime and mime.startswith("image/")):
                    is_image = True

        if not is_image:
            continue

        data_uri, source_name = prepare_image_data_uri(raw_path, base64_data)
        if not data_uri:
            continue

        prompt_parts = [
            "Analyze this evidence image thoroughly for durable personal record keeping.",
            "Extract all legible text and structured facts (business/contractor names, contact info "
            "like phone/email/address, brand, model, serial number, dates, amounts, etc.) and suggested search keywords.",
            "Respond with ONLY a JSON object with keys 'title', 'summary', 'facts' (list of {key, value}), and 'keywords' (list of strings).",
        ]
        context_items = []
        if arguments.get("user_text"):
            context_items.append(f"User note: {arguments['user_text']}")
        if arguments.get("title"):
            context_items.append(f"Title: {arguments['title']}")
        if att.get("description"):
            context_items.append(f"Attachment description: {att['description']}")
        if context_items:
            prompt_parts.append("Context: " + " | ".join(context_items))

        prompt_text = "\n".join(prompt_parts)

        try:
            raw_analysis = query_vision_model(data_uri, prompt_text, timeout=30)
            extracted = parse_structured_extraction(raw_analysis)
        except Exception as exc:
            # Graceful degradation: never abort mutation if vision fails
            sys.stderr.write(f"[mcp_server] Auto-extraction skipped for '{source_name}': {exc}\n")
            sys.stderr.flush()
            continue

        # 1. Title: populate only if not already provided
        if not arguments.get("title") and extracted.get("title"):
            arguments["title"] = extracted["title"]

        # 2. Summary: populate only if not already provided
        if not arguments.get("summary") and extracted.get("summary"):
            arguments["summary"] = extracted["summary"]

        # 3. Facts: merge extracted facts with provenance, user facts take precedence
        existing_facts = []
        raw_facts = arguments.get("facts")
        if isinstance(raw_facts, dict):
            existing_facts = [
                {"key": str(k), "value": str(v), "source": "user", "confidence": "high"}
                for k, v in raw_facts.items()
            ]
        elif isinstance(raw_facts, list):
            for f in raw_facts:
                if isinstance(f, dict) and "key" in f:
                    existing_facts.append(dict(f))

        existing_keys = {
            str(f["key"]).strip().lower(): f
            for f in existing_facts
            if "key" in f
        }

        for ef in extracted.get("facts", []):
            ek = str(ef.get("key", "")).strip()
            ev = str(ef.get("value", "")).strip()
            if ek and ev and ek.lower() not in existing_keys:
                new_fact = {
                    "key": ek,
                    "value": ev,
                    "source": source_name or "image",
                    "confidence": "high",
                }
                existing_facts.append(new_fact)
                existing_keys[ek.lower()] = new_fact

        arguments["facts"] = existing_facts

        # 4. Keywords: merge and deduplicate
        existing_kw = []
        raw_kw = arguments.get("keywords", [])
        if isinstance(raw_kw, list):
            existing_kw = [str(x).strip() for x in raw_kw if str(x).strip()]
        elif isinstance(raw_kw, str):
            existing_kw = [x.strip() for x in raw_kw.split(",") if x.strip()]

        existing_lower = {k.lower() for k in existing_kw}
        for kw in extracted.get("keywords", []):
            kws = str(kw).strip()
            if kws and kws.lower() not in existing_lower:
                existing_kw.append(kws)
                existing_lower.add(kws.lower())

        arguments["keywords"] = existing_kw


def execute_tool(name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Execute the requested archive tool and return the resulting dictionary."""
    ensure_archive_configured()

    if name == "archive_create":
        enrich_spec_with_image_analysis(arguments)
        res = personal_archive.create(arguments)
        return {
            "ok": True,
            "operation": "create",
            "id": res["id"],
            "title": res.get("title") or res["record"].get("title"),
            "path": res["path"],
            "record": res["record"],
            "attachments_added": res.get("attachments_added", []),
            "duplicates": res.get("duplicates", []),
        }

    if name == "archive_search":
        query = str(arguments.get("query", ""))
        limit = int(arguments.get("limit", 10))
        results = personal_archive.search(query, limit)
        return {
            "ok": True,
            "query": query,
            "count": len(results),
            "results": results,
        }

    if name == "archive_show":
        eid = str(arguments.get("id", ""))
        record = personal_archive.load(eid)
        return {
            "ok": True,
            "record": record,
        }

    if name == "archive_add_evidence":
        enrich_spec_with_image_analysis(arguments)
        eid = str(arguments.get("id", ""))
        spec = {k: v for k, v in arguments.items() if k != "id"}
        res = personal_archive.add(eid, spec)
        return {
            "ok": True,
            "operation": "add",
            "id": eid,
            "title": res.get("title") or res["record"].get("title"),
            "path": res["path"],
            "record": res["record"],
            "attachments_added": res.get("attachments_added", []),
            "duplicates": res.get("duplicates", []),
        }

    if name == "archive_set_fact":
        eid = str(arguments.get("id", ""))
        key = str(arguments.get("key", ""))
        val = str(arguments.get("value", ""))
        src = str(arguments.get("source", "user"))
        conf = str(arguments.get("confidence", "high"))
        return personal_archive.setfact(eid, key, val, src, conf)

    if name == "archive_get_attachment":
        aid = str(arguments.get("id", ""))
        m, x = personal_archive.find_att(aid)
        path = str(personal_archive.rdir(m["id"]) / x["stored_relpath"])
        return {
            "ok": True,
            "record": m["id"],
            "attachment": x,
            "path": path,
        }

    if name == "archive_delete":
        eid = str(arguments.get("id", ""))
        return personal_archive.delete(eid)

    if name == "archive_doctor":
        return personal_archive.doctor()

    if name == "archive_inspect_image":
        return inspect_image(arguments)

    raise ValueError(f"Unknown tool: {name}")


def inspect_image(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Inspect an evidence image file using local multimodal vision (Gemma 4 via LM Studio)."""
    raw_path = arguments.get("path")
    base64_data = arguments.get("image_base64")
    user_context = (arguments.get("context") or "").strip()

    if not raw_path and not base64_data:
        raise ValueError("Either 'path' or 'image_base64' is required.")

    data_uri, source_name = prepare_image_data_uri(raw_path, base64_data)
    if not data_uri:
        raise FileNotFoundError(f"Image file not found: {raw_path}")

    prompt_text = (
        "Analyze this evidence image thoroughly for durable personal record keeping.\n"
        "Transcribe and extract all legible information:\n"
        "- Business/Company name and individual/contractor name\n"
        "- Contact details (phone numbers, email addresses, websites, physical addresses)\n"
        "- Brand, manufacturer, model number, serial number, and product codes\n"
        "- Dates, invoice/receipt IDs, dollar amounts, and warranty terms\n"
        "- Dimensions, ratings, materials, or part numbers\n"
        "- A list of 5 to 10 rich search keywords/tags (including categories, trades, and synonyms)\n"
    )
    if user_context:
        prompt_text += f"\nUser request/context: {user_context}\n"
    prompt_text += (
        "\nProvide a clear structured breakdown with headings for "
        "Title Suggestion, Extracted Text, Key Facts, and Search Keywords."
    )

    resolved_path_str = None
    if raw_path and not str(raw_path).startswith("data:image/"):
        try:
            resolved_path_str = str(personal_archive.resolve_attachment_path(str(raw_path).strip()))
        except Exception:
            resolved_path_str = str(raw_path)

    analysis = query_vision_model(data_uri, prompt_text, timeout=60)
    extracted = parse_structured_extraction(analysis)

    return {
        "ok": True,
        "operation": "inspect_image",
        "path": resolved_path_str,
        "analysis": analysis,
        "extracted_facts": extracted.get("facts", []),
        "extracted_keywords": extracted.get("keywords", []),
    }


def read_message(stream) -> Dict[str, Any] | None:
    """Read next JSON-RPC message supporting both line-delimited and Content-Length framed stdio."""
    line = stream.readline()
    if not line:
        return None
    line_str = line.strip()
    if not line_str:
        return read_message(stream)

    if line_str.startswith("Content-Length:"):
        length = int(line_str.split(":", 1)[1].strip())
        while True:
            header = stream.readline().strip()
            if not header:
                break
        body = stream.read(length)
        return json.loads(body)

    return json.loads(line_str)


def write_response(obj: Dict[str, Any]):
    """Write JSON-RPC message to stdout followed by newline and flush."""
    data = json.dumps(obj, ensure_ascii=False)
    sys.stdout.write(data + "\n")
    sys.stdout.flush()


def run_server():
    """Main stdio JSON-RPC loop."""
    sys.stderr.write(f"Personal Archive MCP Server starting (pid {os.getpid()})...\n")
    sys.stderr.flush()

    while True:
        try:
            msg = read_message(sys.stdin)
        except Exception as e:
            sys.stderr.write(f"Error reading message: {e}\n")
            sys.stderr.flush()
            continue

        if msg is None:
            # EOF reached
            break

        msg_id = msg.get("id")
        method = msg.get("method")
        params = msg.get("params") or {}

        # Handle notifications (no id)
        if msg_id is None:
            if method == "notifications/initialized":
                # Notification of successful initialization; no response expected
                pass
            continue

        if method == "initialize":
            write_response(
                {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {
                        "protocolVersion": PROTOCOL_VERSION,
                        "capabilities": {
                            "tools": {},
                        },
                        "serverInfo": {
                            "name": SERVER_NAME,
                            "version": SERVER_VERSION,
                        },
                    },
                }
            )
        elif method == "ping":
            write_response(
                {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {},
                }
            )
        elif method == "tools/list":
            write_response(
                {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {
                        "tools": TOOLS,
                    },
                }
            )
        elif method == "tools/call":
            tool_name = params.get("name")
            arguments = params.get("arguments") or {}
            try:
                result_data = execute_tool(tool_name, arguments)
                write_response(
                    {
                        "jsonrpc": "2.0",
                        "id": msg_id,
                        "result": {
                            "content": [
                                {
                                    "type": "text",
                                    "text": json.dumps(
                                        result_data, indent=2, ensure_ascii=False
                                    ),
                                }
                            ],
                            "isError": False,
                        },
                    }
                )
            except Exception as e:
                err_data = {
                    "ok": False,
                    "error": type(e).__name__,
                    "detail": str(e),
                }
                write_response(
                    {
                        "jsonrpc": "2.0",
                        "id": msg_id,
                        "result": {
                            "content": [
                                {
                                    "type": "text",
                                    "text": json.dumps(
                                        err_data, indent=2, ensure_ascii=False
                                    ),
                                }
                            ],
                            "isError": True,
                        },
                    }
                )
        else:
            write_response(
                {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "error": {
                        "code": -32601,
                        "message": f"Method '{method}' not found",
                    },
                }
            )


if __name__ == "__main__":
    run_server()
