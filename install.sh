#!/usr/bin/env bash
set -euo pipefail
SRC="$(cd "$(dirname "$0")" && pwd)"
DEST="$HOME/.openclaw/workspace/skills/home-archive"
mkdir -p "$(dirname "$DEST")"
if [[ -e "$DEST" ]]; then mv "$DEST" "${DEST}.backup.$(date +%Y%m%d-%H%M%S)"; fi
mkdir -p "$DEST/scripts"
cp "$SRC/SKILL.md" "$DEST/SKILL.md"
cp "$SRC/README.md" "$DEST/README.md"
cp "$SRC/scripts/home_archive.py" "$DEST/scripts/home_archive.py"
chmod +x "$DEST/scripts/home_archive.py"
python3 "$DEST/scripts/home_archive.py" init
echo "Installed $DEST"
echo "Run: openclaw skills list | grep home-archive"
echo "Run: python3 $DEST/scripts/home_archive.py doctor"
