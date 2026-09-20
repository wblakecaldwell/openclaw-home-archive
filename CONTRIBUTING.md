# Contributing

This project is experimental.

## Before committing

1. Run `python3 -m py_compile scripts/home_archive.py`.
2. Run `python3 -m unittest discover -s tests -v`. Use only disposable test data,
   never a real household archive, for additional manual checks.
3. Review `git diff --staged` for personal data, credentials, absolute user paths,
   message contents, logs, and archive attachments.
4. Do not commit the configured `<archive-root>` directory or copies of it.

## Design principle

The on-disk Home Archive is authoritative. External systems such as Apple Photos
are projections and must be rebuildable from the archive.

## Automated tests

The suite uses Python's standard-library `unittest`; no extra packages or running
OpenClaw installation are required. Run from the repository root:

```bash
python3 -m unittest discover -s tests -v
```

Run a single module or case while developing:

```bash
python3 -m unittest tests.test_archive -v
python3 -m unittest tests.test_archive.ArchiveTests.test_merge_with_self_is_rejected_without_changes -v
```

- `test_facts.py` covers fact supersession, searchable text, filename components,
  and projected metadata.
- `test_archive.py` exercises real filesystem operations, evidence preservation,
  search, merges, history, sequence allocation, interrupted JSON replacement, and doctor.
- `test_cli.py` invokes the CLI as a subprocess and checks JSON responses, exit
  statuses, persisted identifiers, and failure/repair flows.
- `test_photos.py` tests synchronization and rebuild orchestration with mocked
  Photos operations.

Each test creates and cleans up its own temporary directory. The shared helper in
`tests/support.py` sets `HOME_ARCHIVE_ROOT` before loading a fresh script module,
so all derived paths point to the temporary archive. CLI subprocesses receive the
same explicit environment. Direct tests block the AppleScript boundary, and the
subprocess helper allows only commands that do not invoke Photos.

Create synthetic fixtures through the helper instead of adding household files to
the repository. Test observable outcomes: preserved bytes, persisted metadata,
event history, and clear failures. For a bug fix, first add a test that fails on
the old behavior, then make the smallest fix that satisfies the intended contract.

The Photos tests verify Python orchestration, including passing only the IDs
returned by managed-asset selection to deletion. They do not execute AppleScript
or prove that Photos itself selects the right assets. Real Photos integration
requires a separate, explicitly authorized test environment.

These tests also do not run the conversational agent. The repair/rerun regression
proves that changing a staged spec does not create a record; it cannot prove that
an agent will rerun the command or describe the result correctly. Relative-date
coverage verifies persistence of a supplied date and original wording, not the
agent's interpretation of "today". Those require separate OpenClaw scenarios.
