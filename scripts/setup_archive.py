#!/usr/bin/env python3
"""Configure the archive location through OpenClaw's config CLI during installation."""

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

CONFIG_KEY = "skills.entries.home-archive.env.HOME_ARCHIVE_ROOT"


def read_root():
    """Treat only a recognized missing-key response as missing configuration."""
    result = subprocess.run(
        ["openclaw", "config", "get", CONFIG_KEY, "--json"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        diagnostic = result.stdout + result.stderr
        if any(
            message in diagnostic
            for message in (
                f"Config path not found: {CONFIG_KEY}",
                f"Config path is valid but unset: {CONFIG_KEY}",
            )
        ):
            return None
        raise ValueError(
            "Could not read OpenClaw configuration. Run openclaw config get "
            + CONFIG_KEY
            + " to inspect the error."
        )
    value = json.loads(result.stdout)
    if value is None or isinstance(value, str) and not value.strip():
        return None
    if not isinstance(value, str):
        raise ValueError("Configured HOME_ARCHIVE_ROOT must be a path string.")
    return value


def validate_root(value, skill_directory):
    """Require an explicit absolute location that survives skill replacement."""
    if not value or not value.strip():
        raise ValueError("An archive location is required; there is no default.")
    path = Path(os.path.expanduser(value))
    if not path.is_absolute() or "<archive-root>" in value:
        raise ValueError("Use an absolute archive path, replacing <archive-root>.")
    if path.exists() and not path.is_dir():
        raise ValueError("The archive location must be a directory.")
    resolved = path.resolve()
    # Check lexical containment as well as symlink targets before deletion.
    skill = Path(skill_directory)
    for candidate, destination in (
        (Path(os.path.abspath(path)), Path(os.path.abspath(skill))),
        (resolved, skill.resolve()),
    ):
        if candidate == destination or destination in candidate.parents:
            raise ValueError(
                "The archive must be outside the installed skill directory."
            )
    return str(path)


def configure(explicit, skill_directory):
    existing = read_root()
    if existing is not None:
        root = validate_root(existing, skill_directory)
        if explicit is not None:
            requested = validate_root(explicit, skill_directory)
            if Path(requested).resolve() != Path(root).resolve():
                raise ValueError(
                    "A different archive is already configured. Change it explicitly "
                    "with openclaw config set; installation will not redirect it."
                )
        print(f"HOME_ARCHIVE_ROOT={root} (existing OpenClaw configuration)")
        shell_value = os.environ.get("HOME_ARCHIVE_ROOT")
        if shell_value and shell_value != existing:
            print(
                "The shell HOME_ARCHIVE_ROOT differs; direct CLI commands use the shell value."
            )
        return root

    root = explicit
    if root is None:
        if not sys.stdin.isatty():
            raise ValueError(
                "No archive is configured. Use --archive-root for noninteractive installation."
            )
        candidate = os.environ.get("HOME_ARCHIVE_ROOT")
        if candidate and candidate.strip():
            print(f"Shell HOME_ARCHIVE_ROOT={candidate}")
            if input(
                "Save this location in OpenClaw configuration? [y/N] "
            ).strip().lower() in ("y", "yes"):
                root = candidate
        if root is None:
            root = input("Archive directory (absolute path, no default): ")
    root = validate_root(root, skill_directory)
    result = subprocess.run(
        ["openclaw", "config", "set", CONFIG_KEY, json.dumps(root), "--strict-json"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        raise ValueError(
            "OpenClaw could not save the archive location. Installation stopped."
        )
    if read_root() != root:
        raise ValueError(
            "OpenClaw did not return the saved archive location. Installation stopped."
        )
    print(f"HOME_ARCHIVE_ROOT={root} (saved in OpenClaw configuration)")
    return root


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive-root")
    parser.add_argument("--skill-directory", required=True)
    args = parser.parse_args()
    try:
        configure(args.archive_root, args.skill_directory)
    except (ValueError, OSError, EOFError) as error:
        print(f"Archive setup failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
