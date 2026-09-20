# OpenClaw Home Archive

> **Status:** Experimental / pre-release. Back up important data and review changes before relying on this skill.

Authoritative root: `<archive-root>`, configured through `HOME_ARCHIVE_ROOT`. No user taxonomy; durable entity records accumulate facts and attachments over time. Originals are immutable, facts retain provenance, event history is append-only JSONL, attachments are SHA-256 deduplicated, and Photos is rebuildable.

## Install
```bash
unzip home-archive-skill.zip
cd home-archive-skill
./install.sh
```
Installs to `~/.openclaw/workspace/skills/home-archive/`.

Choose an archive directory outside this repository. Throughout these docs,
`<archive-root>` is a placeholder for its absolute path. Replace it below before running:

```bash
export HOME_ARCHIVE_ROOT="<archive-root>"
```

Set the same environment variable in the environment that launches OpenClaw so its
CLI commands use the same archive. The export above applies to the current shell
and its child processes. The CLI retains its existing fallback when the variable is unset;
set it explicitly to select your archive location. Changing it selects a different directory
and does not move existing archive data.

Then run:
```bash
openclaw skills list | grep home-archive
python3 ~/.openclaw/workspace/skills/home-archive/scripts/home_archive.py doctor
```
The first Photos operation may trigger macOS Automation permission for Photos. Archive operations still work without Photos permission.


## Privacy and repository hygiene

The repository contains the skill code only. Household archive data is stored outside
the repository at the configured `<archive-root>`.

Do not commit archive data, logs, `.env` files, credentials, message exports, or
other personal material. The included `.gitignore` provides additional protection,
but it is not a substitute for reviewing changes before committing.

## License

MIT. See `LICENSE`.


## Development with coding agents

Before making implementation changes, read [`AGENTS.md`](AGENTS.md) and
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md). They document the repository invariants,
storage model, safety boundaries, known first integration regression, and current development
priorities.
