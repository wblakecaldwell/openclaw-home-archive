#!/usr/bin/env bash
set -euo pipefail
SRC="$(cd "$(dirname "$0")" && pwd -P)"
DEST="$HOME/.openclaw/workspace/skills/home-archive"
setup_args=(--skill-directory "$DEST")
while [[ $# -gt 0 ]]; do
  case "$1" in
    --archive-root)
      if [[ $# -lt 2 ]]; then
        echo "--archive-root requires a location." >&2
        exit 1
      fi
      setup_args+=(--archive-root "$2")
      shift 2
      ;;
    --help|-h)
      echo 'Usage: ./install.sh [--archive-root <absolute-path>]'
      echo 'Reuse OpenClaw configuration, or prompt for a location when interactive.'
      exit 0
      ;;
    *) echo "Unknown argument: $1" >&2; exit 1 ;;
  esac
done
command -v openclaw >/dev/null || { echo 'OpenClaw must be installed and on PATH.' >&2; exit 1; }

# Do not remove the checkout supplying the installation files.
if [[ -d "$DEST" && ! -L "$DEST" ]]; then
  installed_root="$(cd "$DEST" && pwd -P)"
  case "$SRC/" in
    "$installed_root/"*)
      echo "Run install.sh from a checkout outside the installed skill directory." >&2
      exit 1
      ;;
  esac
fi

mkdir -p "$(dirname "$DEST")"
# Prepare the full replacement before deleting an existing installation.
staged_skill="$(mktemp -d "$(dirname "$DEST")/.home-archive-install.XXXXXX")"
trap 'rm -rf -- "$staged_skill"' EXIT
mkdir -p "$staged_skill/scripts"
cp "$SRC/SKILL.md" "$staged_skill/SKILL.md"
cp "$SRC/README.md" "$staged_skill/README.md"
cp "$SRC/scripts/home_archive.py" "$staged_skill/scripts/home_archive.py"
chmod +x "$staged_skill/scripts/home_archive.py"

# Configure only after staging succeeds, and before removing the old installation.
python3 "$SRC/scripts/setup_archive.py" "${setup_args[@]}"

# If DEST is a symlink, remove only the link, leaving its target untouched.
rm -rf -- "$DEST"
mv "$staged_skill" "$DEST"
echo "Installed $DEST"
echo "Run: openclaw skills list | grep home-archive"
echo "Archive initialization is separate; see README.md for first-use commands."
