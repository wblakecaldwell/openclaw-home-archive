# Contributing

This project is experimental.

## Before committing

1. Run `python3 -m py_compile scripts/home_archive.py`.
2. Run the CLI against disposable test data, never a real household archive.
3. Review `git diff --staged` for personal data, credentials, absolute user paths,
   message contents, logs, and archive attachments.
4. Do not commit `~/Documents/OpenClaw/HomeArchive` or copies of it.

## Design principle

The on-disk Home Archive is authoritative. External systems such as Apple Photos
are projections and must be rebuildable from the archive.
