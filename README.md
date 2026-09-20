# OpenClaw Home Archive

> **Status:** Experimental / pre-release. Back up important data and review changes before relying on this skill.

Authoritative root: `~/Documents/OpenClaw/HomeArchive`. No user taxonomy; durable entity records accumulate facts and attachments over time. Originals are immutable, facts retain provenance, event history is append-only JSONL, attachments are SHA-256 deduplicated, and Photos is rebuildable.

## Install
```bash
unzip home-archive-skill.zip
cd home-archive-skill
./install.sh
```
Installs to `~/.openclaw/workspace/skills/home-archive/`. Then run:
```bash
openclaw skills list | grep home-archive
python3 ~/.openclaw/workspace/skills/home-archive/scripts/home_archive.py doctor
```
The first Photos operation may trigger macOS Automation permission for Photos. Archive operations still work without Photos permission.


## Privacy and repository hygiene

The repository contains the skill code only. Household archive data is stored outside
the repository at `~/Documents/OpenClaw/HomeArchive`.

Do not commit archive data, logs, `.env` files, credentials, message exports, or
other personal material. The included `.gitignore` provides additional protection,
but it is not a substitute for reviewing changes before committing.

## License

MIT. See `LICENSE`.
