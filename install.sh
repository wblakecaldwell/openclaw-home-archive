#!/usr/bin/env bash
# install.sh — Installs and manages Personal Archive software artifacts and dedicated agent workspace.
# Personal Archive does NOT automatically administer or rewrite OpenClaw configuration.
# For OpenClaw configuration procedures, see docs/OPENCLAW_SETUP.md.

set -euo pipefail

SRC="$(cd "$(dirname "$0")" && pwd -P)"
DEST="${SKILL_DIRECTORY:-$HOME/.openclaw/workspace/skills/personal-archive}"
AGENT_WS="${AGENT_WORKSPACE:-$HOME/.openclaw/workspaces/archivist}"
MAIN_AGENTS="${MAIN_AGENTS_FILE:-${MAIN_WORKSPACE:-$HOME/.openclaw/workspace}/AGENTS.md}"

archive_root=""
mode="install"
update_agents_context="false"
reindex="false"
dry_run="false"
force="false"
record_id=""

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
    --update-agents-context|--update-main-directives)
      update_agents_context="true"
      shift
      ;;
    --main-agents-file)
      if [[ $# -lt 2 || -z "$2" ]]; then
        echo "--main-agents-file requires a non-empty path." >&2
        exit 1
      fi
      MAIN_AGENTS="$2"
      shift 2
      ;;
    --reindex)
      reindex="true"
      shift
      ;;
    --dry-run)
      dry_run="true"
      shift
      ;;
    --force)
      force="true"
      shift
      ;;
    --record)
      if [[ $# -lt 2 || -z "$2" ]]; then
        echo "--record requires a record ID argument." >&2
        exit 1
      fi
      record_id="$2"
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
      echo '  --archive-root <path>     Specify absolute archive directory to initialize or verify'
      echo '  --update-agents-context   Install or update Personal Archive routing directives in main AGENTS.md'
      echo '  --main-agents-file <path> Path to main agent AGENTS.md (default: ~/.openclaw/workspace/AGENTS.md)'
      echo '  --reindex                 Reindex archive records with local Gemma 4 vision to backfill facts/keywords'
      echo '  --dry-run                 Simulate reindexing without writing any changes to disk (used with --reindex)'
      echo '  --force                   Allow vision model to supersede automated facts (used with --reindex)'
      echo '  --record <id>             Reindex a specific record ID instead of the entire archive'
      echo '  --check                   Read-only inspection of OpenClaw Personal Archive integration health'
      echo '  --uninstall               Safely remove Personal Archive software artifacts (preserves archive data)'
      echo '  --help, -h                Show this help message'
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
  check_args=(--skill-directory "$DEST" --workspace-directory "$AGENT_WS" --main-agents-file "$MAIN_AGENTS")
  if [[ -n "$archive_root" ]]; then
    check_args+=(--archive-root "$archive_root")
  fi
  python3 "$SRC/scripts/check_openclaw.py" "${check_args[@]}"
  exit $?
fi

# Handle --uninstall mode
if [[ "$mode" == "uninstall" ]]; then
  echo "==> Removing Personal Archive software artifacts..."

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

  # 3. If requested, remove routing directives from main AGENTS.md
  if [[ "$update_agents_context" == "true" ]]; then
    if [[ -f "$SRC/scripts/manage_directives.py" ]]; then
      echo "    Removing routing directives from: $MAIN_AGENTS"
      python3 "$SRC/scripts/manage_directives.py" remove --target "$MAIN_AGENTS"
    fi
  fi

  # Determine archive root read-only for reporting
  configured_root=""
  if [[ -n "$archive_root" ]]; then
    configured_root="$archive_root"
  elif configured_json="$(openclaw config get skills.entries.personal-archive.env.PERSONAL_ARCHIVE_ROOT --json 2>/dev/null)" && [[ -n "$configured_json" && "$configured_json" != "null" ]]; then
    configured_root="$(python3 -c "import json, sys; print(json.loads(sys.argv[1]) or '')" "$configured_json" 2>/dev/null || echo "")"
  fi

  echo ""
  echo "Personal Archive software artifacts uninstalled successfully."
  if [[ -n "$configured_root" ]]; then
    echo "NOTE: Durable archive data at '$configured_root' was preserved untouched."
  else
    echo "NOTE: Any durable personal archive data was preserved untouched."
  fi
  echo "NOTE: Apple Photos assets were preserved untouched."
  echo ""
  if [[ "$update_agents_context" == "true" ]]; then
    echo "Personal Archive routing directives removed from main AGENTS.md."
  else
    echo "OpenClaw configuration and main agent directives may still reference Personal Archive."
    echo "To remove main agent directives automatically, rerun with --update-agents-context."
  fi
  echo "To remove remaining OpenClaw configuration entries, please follow:"
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
staged_skill="$(mktemp -d "$(dirname "$DEST")/.personal-archive-install.XXXXXX")"
trap 'rm -rf -- "$staged_skill"' EXIT
mkdir -p "$staged_skill/scripts"
cp "$SRC/SKILL.md" "$staged_skill/SKILL.md"
cp "$SRC/README.md" "$staged_skill/README.md"
cp "$SRC/scripts/personal_archive.py" "$staged_skill/scripts/personal_archive.py"
chmod +x "$staged_skill/scripts/personal_archive.py"
if [[ -f "$SRC/scripts/mcp_server.py" ]]; then
  cp "$SRC/scripts/mcp_server.py" "$staged_skill/scripts/mcp_server.py"
  chmod +x "$staged_skill/scripts/mcp_server.py"
fi
if [[ -f "$SRC/scripts/manage_directives.py" ]]; then
  cp "$SRC/scripts/manage_directives.py" "$staged_skill/scripts/manage_directives.py"
  chmod +x "$staged_skill/scripts/manage_directives.py"
fi
if [[ -f "$SRC/scripts/reindex_archive.py" ]]; then
  cp "$SRC/scripts/reindex_archive.py" "$staged_skill/scripts/reindex_archive.py"
  chmod +x "$staged_skill/scripts/reindex_archive.py"
fi

# If DEST is a symlink, remove only the link, leaving its target untouched.
rm -rf -- "$DEST"
mv "$staged_skill" "$DEST"
echo "Installed skill to: $DEST"

# 3. Provision / update dedicated agent workspace
mkdir -p "$AGENT_WS"
if [[ -d "$SRC/openclaw/workspace-archivist" ]]; then
  cp "$SRC/openclaw/workspace-archivist/AGENTS.md" "$AGENT_WS/AGENTS.md"
  cp "$SRC/openclaw/workspace-archivist/IDENTITY.md" "$AGENT_WS/IDENTITY.md"
  rm -f "$AGENT_WS/MEMORY.md" "$AGENT_WS/USER.md"
  echo "Provisioned agent workspace at: $AGENT_WS"
fi

# 3b. Install / update main agent routing directives if requested
if [[ "$update_agents_context" == "true" ]]; then
  echo "Updating main agent routing directives in: $MAIN_AGENTS"
  python3 "$SRC/scripts/manage_directives.py" install \
    --target "$MAIN_AGENTS" \
    --source "$SRC/openclaw/main-routing-instructions.md"
fi

# 4. Handle Archive Root (Initialize or Preserve; NEVER delete)
resolved_archive_root=""
if [[ -n "$archive_root" ]]; then
  resolved_archive_root="$archive_root"
elif [[ -n "${PERSONAL_ARCHIVE_ROOT:-}" ]]; then
  resolved_archive_root="$PERSONAL_ARCHIVE_ROOT"
elif configured_json="$(openclaw config get skills.entries.personal-archive.env.PERSONAL_ARCHIVE_ROOT --json 2>/dev/null)" && [[ -n "$configured_json" && "$configured_json" != "null" ]]; then
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
p = Path(os.path.realpath(os.path.expanduser(raw)))
if not Path(os.path.expanduser(raw)).is_absolute():
    sys.exit(1)
dest = Path(os.path.realpath(os.path.expanduser(sys.argv[2])))
for cand in (p, Path(os.path.abspath(os.path.expanduser(raw)))):
    for tgt in (dest, Path(os.path.abspath(os.path.expanduser(sys.argv[2])))):
        if cand == tgt or tgt in cand.parents:
            sys.exit(1)
' "$resolved_archive_root" "$DEST"; then
    echo "Invalid archive path: $resolved_archive_root (must be an absolute path outside the skill directory)" >&2
    exit 1
  fi

  expanded_root="$(python3 -c "import os, sys; print(os.path.expanduser(sys.argv[1]))" "$resolved_archive_root")"

  if [[ ! -d "$expanded_root" ]]; then
    echo "Initializing new Personal Archive at: $expanded_root"
    PERSONAL_ARCHIVE_ROOT="$expanded_root" python3 "$DEST/scripts/personal_archive.py" init
  else
    echo "Preserving existing Personal Archive at: $expanded_root"
  fi

  echo "Running Personal Archive doctor check..."
  PERSONAL_ARCHIVE_ROOT="$expanded_root" python3 "$DEST/scripts/personal_archive.py" doctor
fi

echo ""
# 5. Tell the user whether OpenClaw integration is complete
check_args=(--skill-directory "$DEST" --workspace-directory "$AGENT_WS" --main-agents-file "$MAIN_AGENTS" --summary)
if [[ -n "$resolved_archive_root" ]]; then
  check_args+=(--archive-root "$resolved_archive_root")
fi

if python3 "$SRC/scripts/check_openclaw.py" "${check_args[@]}"; then
  echo "==> Installation complete. OpenClaw Personal Archive integration is verified!"
  echo "    Skill:     $DEST"
  echo "    Workspace: $AGENT_WS"
  echo "    Archive:   ${resolved_archive_root:-Configured in OpenClaw}"
  echo ""
  echo "If you recently updated OpenClaw settings, restart the Gateway:"
  echo "    openclaw gateway restart"
else
  echo "==> Personal Archive software artifacts and workspace installed."
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

# 6. Reindex archive records if requested
if [[ "$reindex" == "true" ]]; then
  echo ""
  echo "==> Reindexing Personal Archive records with local vision model..."
  reindex_target_root="${expanded_root:-${resolved_archive_root:-}}"
  if [[ -z "$reindex_target_root" && -n "${PERSONAL_ARCHIVE_ROOT:-}" ]]; then
    reindex_target_root="$PERSONAL_ARCHIVE_ROOT"
  fi
  reindex_cmd=(python3 "$DEST/scripts/reindex_archive.py")
  if [[ -n "$reindex_target_root" ]]; then
    reindex_cmd+=(--root "$reindex_target_root")
  fi
  if [[ "$dry_run" == "true" ]]; then
    reindex_cmd+=(--dry-run)
  fi
  if [[ "$force" == "true" ]]; then
    reindex_cmd+=(--force)
  fi
  if [[ -n "$record_id" ]]; then
    reindex_cmd+=(--record "$record_id")
  fi
  if [[ -n "$reindex_target_root" ]]; then
    PERSONAL_ARCHIVE_ROOT="$reindex_target_root" "${reindex_cmd[@]}"
  else
    "${reindex_cmd[@]}"
  fi
fi
