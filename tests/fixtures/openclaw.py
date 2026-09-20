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
    value = config
    for part in args[2].split("."):
        if part not in value:
            print("Config path not found: " + args[2], file=sys.stderr)
            sys.exit(1)
        value = value[part]
    print(json.dumps(value))
elif args[:2] == ["config", "set"]:
    if os.environ.get("TEST_OPENCLAW_WRITE_FAILURE"):
        sys.exit(1)
    assert args[-1] == "--strict-json"
    value = config
    parts = args[2].split(".")
    for part in parts[:-1]:
        value = value.setdefault(part, {})
    value[parts[-1]] = json.loads(args[3])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config))
else:
    raise AssertionError(args)
