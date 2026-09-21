#!/usr/bin/env bash
# install.sh — Installs and manages Home Archive software artifacts and dedicated agent workspace.
# Home Archive does NOT automatically administer or rewrite OpenClaw configuration.
# For OpenClaw configuration procedures, see docs/OPENCLAW_SETUP.md.

set -euo pipefail

SRC="$(cd "$(dirname "$0")" && pwd -P)"
DEST="${SKILL_DIRECTORY:-$HOME/.openclaw/workspace/skills/home-archive}"
AGENT_WS="${AGENT_WORKSPACE:-$HOME/.openclaw/workspaces/home-archive}"

archive_root=""
mode="install"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --archive-root)
      if [[ $# -lt 2 || -z "$2" ]]; then
        echo "--archive-root requires a non-empty absolute path." >&2
        exit 1
      fi
      archive_root="$2"
      shift 2
      ;;
    --check)
      mode="check"
      shift
      ;;
    --uninstall)
      mode="uninstall"
      shift
      ;;
    --help|-h)
      echo 'Usage: ./install.sh [options]'
      echo ''
      echo 'Options:'
      echo '  --archive-root <path>  Specify absolute archive directory to initialize or verify'
      echo '  --check                Read-only inspection of OpenClaw Home Archive integration health'
      echo '  --uninstall            Safely remove Home Archive software artifacts (preserves archive data)'
      echo '  --help, -h             Show this help message'
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 1
      ;;
  esac
done

command -v openclaw >/dev/null || { echo 'OpenClaw must be installed and on PATH.' >&2; exit 1; }
command -v python3 >/dev/null || { echo 'python3 must be installed and on PATH.' >&2; exit 1; }

# Handle --check mode (purely read-only inspection)
if [[ "$mode" == "check" ]]; then
  check_args=(--skill-directory "$DEST" --workspace-directory "$AGENT_WS")
  if [[ -n "$archive_root" ]]; then
    check_args+=(--archive-root "$archive_root")
  fi
  python3 "$SRC/scripts/check_openclaw.py" "${check_args[@]}"
  exit $?
fi

# Handle --uninstall mode
if [[ "$mode" == "uninstall" ]]; then
  echo "==> Removing Home Archive software artifacts..."

  # 1. Remove installed skill
  if [[ -d "$DEST" || -L "$DEST" ]]; then
    rm -rf -- "$DEST"
    echo "    Removed skill directory: $DEST"
  fi

  # 2. Remove dedicated agent workspace
  if [[ -d "$AGENT_WS" ]]; then
    rm -rf -- "$AGENT_WS"
    echo "    Removed agent workspace: $AGENT_WS"
  fi

  # Determine archive root read-only for reporting
  configured_root=""
  if [[ -n "$archive_root" ]]; then
    configured_root="$archive_root"
  elif configured_json="$(openclaw config get skills.entries.home-archive.env.HOME_ARCHIVE_ROOT --json 2>/dev/null)" && [[ -n "$configured_json" && "$configured_json" != "null" ]]; then
    configured_root="$(python3 -c "import json, sys; print(json.loads(sys.argv[1]) or '')" "$configured_json" 2>/dev/null || echo "")"
  fi

  echo ""
  echo "Home Archive software artifacts uninstalled successfully."
  if [[ -n "$configured_root" ]]; then
    echo "NOTE: Durable archive data at '$configured_root' was preserved untouched."
  else
    echo "NOTE: Any durable household archive data was preserved untouched."
  fi
  echo "NOTE: Apple Photos assets were preserved untouched."
  echo ""
  echo "OpenClaw configuration and main agent directives may still reference Home Archive."
  echo "To remove those OpenClaw references, please follow:"
  echo "    docs/OPENCLAW_SETUP.md#uninstall"
  exit 0
fi

# Standard Install / Update Mode

# Validate explicit --archive-root before staging replacement files
if [[ -n "$archive_root" ]]; then
  if ! python3 -c '
import os, sys
from pathlib import Path

raw = sys.argv[1]
if not raw or not raw.strip() or "<archive-root>" in raw:
    sys.exit(1)
p = Path(os.path.realpath(os.path.expanduser(raw)))
if not Path(os.path.expanduser(raw)).is_absolute():
    sys.exit(1)
dest = Path(os.path.realpath(os.path.expanduser(sys.argv[2])))
for cand in (p, Path(os.path.abspath(os.path.expanduser(raw)))):
    for tgt in (dest, Path(os.path.abspath(os.path.expanduser(sys.argv[2])))):
        if cand == tgt or tgt in cand.parents:
            sys.exit(1)
' "$archive_root" "$DEST"; then
    echo "Invalid archive path: $archive_root (must be an absolute path outside the skill directory)" >&2
    exit 1
  fi
fi

# 1. Do not remove the checkout supplying the installation files.
if [[ -d "$DEST" && ! -L "$DEST" ]]; then
  installed_root="$(cd "$DEST" && pwd -P)"
  case "$SRC/" in
    "$installed_root/"*)
      echo "Run install.sh from a checkout outside the installed skill directory." >&2
      exit 1
      ;;
  esac
fi

# 2. Stage and install skill files
mkdir -p "$(dirname "$DEST")"
staged_skill="$(mktemp -d "$(dirname "$DEST")/.home-archive-install.XXXXXX")"
trap 'rm -rf -- "$staged_skill"' EXIT
mkdir -p "$staged_skill/scripts"
cp "$SRC/SKILL.md" "$staged_skill/SKILL.md"
cp "$SRC/README.md" "$staged_skill/README.md"
cp "$SRC/scripts/home_archive.py" "$staged_skill/scripts/home_archive.py"
chmod +x "$staged_skill/scripts/home_archive.py"

# If DEST is a symlink, remove only the link, leaving its target untouched.
rm -rf -- "$DEST"
mv "$staged_skill" "$DEST"
echo "Installed skill to: $DEST"

# 3. Provision / update dedicated agent workspace
mkdir -p "$AGENT_WS"
if [[ -d "$SRC/openclaw/workspace-home-archive" ]]; then
  cp "$SRC/openclaw/workspace-home-archive/AGENTS.md" "$AGENT_WS/AGENTS.md"
  cp "$SRC/openclaw/workspace-home-archive/IDENTITY.md" "$AGENT_WS/IDENTITY.md"
  rm -f "$AGENT_WS/MEMORY.md" "$AGENT_WS/USER.md"
  echo "Provisioned agent workspace at: $AGENT_WS"
fi

# 4. Handle Archive Root (Initialize or Preserve; NEVER delete)
resolved_archive_root=""
if [[ -n "$archive_root" ]]; then
  resolved_archive_root="$archive_root"
elif [[ -n "${HOME_ARCHIVE_ROOT:-}" ]]; then
  resolved_archive_root="$HOME_ARCHIVE_ROOT"
elif configured_json="$(openclaw config get skills.entries.home-archive.env.HOME_ARCHIVE_ROOT --json 2>/dev/null)" && [[ -n "$configured_json" && "$configured_json" != "null" ]]; then
  resolved_archive_root="$(python3 -c "import json, sys; print(json.loads(sys.argv[1]) or '')" "$configured_json" 2>/dev/null || echo "")"
fi

if [[ -n "$resolved_archive_root" ]]; then
  # Validate location
  if ! python3 -c '
import os, sys
from pathlib import Path

raw = sys.argv[1]
if not raw or not raw.strip() or "<archive-root>" in raw:
    sys.exit(1)
p = Path(os.path.expanduser(raw))
if not p.is_absolute():
    sys.exit(1)
dest = Path(os.path.expanduser(sys.argv[2])).resolve()
# Check lexical containment and symlink resolved containment
for candidate in (p, p.resolve() if p.exists() else p):
    for target in (dest, dest.resolve()):
        try:
            if candidate == target or target in candidate.parents:
                sys.exit(1)
        except Exception:
            pass
' "$resolved_archive_root" "$DEST"; then
    echo "Invalid archive path: $resolved_archive_root (must be an absolute path outside the skill directory)" >&2
    exit 1
  fi

  expanded_root="$(python3 -c "import os, sys; print(os.path.expanduser(sys.argv[1]))" "$resolved_archive_root")"

  if [[ ! -d "$expanded_root" ]]; then
    echo "Initializing new Home Archive at: $expanded_root"
    HOME_ARCHIVE_ROOT="$expanded_root" python3 "$DEST/scripts/home_archive.py" init
  else
    echo "Preserving existing Home Archive at: $expanded_root"
  fi

  echo "Running Home Archive doctor check..."
  HOME_ARCHIVE_ROOT="$expanded_root" python3 "$DEST/scripts/home_archive.py" doctor
fi

echo ""
# 5. Tell the user whether OpenClaw integration is complete
check_args=(--skill-directory "$DEST" --workspace-directory "$AGENT_WS" --summary)
if [[ -n "$resolved_archive_root" ]]; then
  check_args+=(--archive-root "$resolved_archive_root")
fi

if python3 "$SRC/scripts/check_openclaw.py" "${check_args[@]}"; then
  echo "==> Installation complete. OpenClaw Home Archive integration is verified!"
  echo "    Skill:     $DEST"
  echo "    Workspace: $AGENT_WS"
  echo "    Archive:   ${resolved_archive_root:-Configured in OpenClaw}"
  echo ""
  echo "If you recently updated OpenClaw settings, restart the Gateway:"
  echo "    openclaw gateway restart"
else
  echo "==> Home Archive software artifacts and workspace installed."
  echo "    Skill:     $DEST"
  echo "    Workspace: $AGENT_WS"
  echo ""
  echo "OpenClaw configuration is not yet complete."
  echo "Please follow the setup instructions in:"
  echo "    docs/OPENCLAW_SETUP.md"
  echo ""
  echo "Once configured, verify integration health with:"
  echo "    ./install.sh --check"
fi
