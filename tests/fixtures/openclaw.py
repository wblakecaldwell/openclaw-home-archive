"""Minimal config CLI double; never reads the user's OpenClaw configuration."""

import json
import os
from pathlib import Path
import sys

path = Path(os.environ["TEST_OPENCLAW_CONFIG"])
args = sys.argv[1:]
if os.environ.get("TEST_OPENCLAW_READ_FAILURE") and args[:2] == ["config", "get"]:
    print("Simulated config read failure", file=sys.stderr)
    sys.exit(1)
config = json.loads(path.read_text()) if path.exists() else {}
if args[:2] == ["config", "get"]:
    subargs = [a for a in args[2:] if not a.startswith("--")]
    if not subargs:
        print(json.dumps(config))
        sys.exit(0)
    key = subargs[0]
    value = config
    for part in key.split("."):
        if not isinstance(value, dict) or part not in value:
            print("Config path not found: " + key, file=sys.stderr)
            sys.exit(1)
        value = value[part]
    if os.environ.get("TEST_OPENCLAW_REDACT_SECRETS"):
        if key.startswith("mcp.servers.personal-archive") or key.startswith("skills.entries.personal-archive"):
            if isinstance(value, dict) and "env" in value and isinstance(value["env"], dict):
                value = dict(value)
                value["env"] = {k: "__OPENCLAW_REDACTED__" for k in value["env"]}
            elif isinstance(value, str) and any(x in key for x in ("ROOT", "URL", "MODEL", "TOKEN")):
                value = "__OPENCLAW_REDACTED__"
    print(json.dumps(value))
elif args[:2] == ["config", "set"]:
    if os.environ.get("TEST_OPENCLAW_WRITE_FAILURE"):
        sys.exit(1)
    key = args[2]
    val_str = args[3]
    value = config
    parts = key.split(".")
    for part in parts[:-1]:
        value = value.setdefault(part, {})
    value[parts[-1]] = json.loads(val_str)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config))
elif args[:2] == ["config", "unset"]:
    if os.environ.get("TEST_OPENCLAW_WRITE_FAILURE"):
        sys.exit(1)
    key = args[2]
    parts = key.split(".")
    value = config
    for part in parts[:-1]:
        if not isinstance(value, dict) or part not in value:
            break
        value = value[part]
    else:
        if isinstance(value, dict) and parts[-1] in value:
            del value[parts[-1]]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config))
elif args[:2] == ["config", "validate"]:
    if not path.exists():
        sys.exit(0)
    try:
        json.loads(path.read_text())
        print("Configuration syntax is valid.")
        sys.exit(0)
    except Exception as e:
        print(f"Validation error: {e}", file=sys.stderr)
        sys.exit(1)
elif args[:2] == ["agents", "list"]:
    entries = config.get("agents", {}).get("entries", {})
    print("Agents:")
    for aid in entries:
        print(f"- {aid}")
elif args[:2] == ["skills", "list"]:
    entries = config.get("skills", {}).get("entries", {})
    for sid in entries:
        print(f"{sid} (configured)")
else:
    raise AssertionError(args)

