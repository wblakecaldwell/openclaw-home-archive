#!/usr/bin/env python3
"""OpenClaw Personal Archive - Model Context Protocol (MCP) Stdio Server.

Implements JSON-RPC 2.0 stdio transport adhering to the MCP 2024-11-05 specification.
Exposes native archive tools directly to OpenClaw agents without requiring shell exec.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict

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
            "Use this when preserving receipts, products, appliances, contracts, or household items."
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
            "Appends to event history without overwriting previous evidence."
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
]


def ensure_archive_configured():
    """Ensure personal_archive has resolved its root from PERSONAL_ARCHIVE_ROOT."""
    if personal_archive.ROOT is None:
        personal_archive.configure_root()


def execute_tool(name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Execute the requested archive tool and return the resulting dictionary."""
    ensure_archive_configured()

    if name == "archive_create":
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

    raise ValueError(f"Unknown tool: {name}")


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
