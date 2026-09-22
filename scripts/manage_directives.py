#!/usr/bin/env python3
"""Manage OpenClaw Personal Archive routing directives in the main agent's AGENTS.md."""

import argparse
import os
from pathlib import Path
import sys
import tempfile

START_MARKER = "<!-- BEGIN OPENCLAW PERSONAL ARCHIVE MANAGED ROUTING DIRECTIVES -->"
END_MARKER = "<!-- END OPENCLAW PERSONAL ARCHIVE MANAGED ROUTING DIRECTIVES -->"


def find_default_source() -> Path:
    """Locate the canonical source template in the repository or installed skill."""
    script_dir = Path(__file__).resolve().parent
    candidates = [
        script_dir.parent / "openclaw/main-routing-instructions.md",
        script_dir.parent / "main-routing-instructions.md",
    ]
    for cand in candidates:
        if cand.exists():
            return cand
    return candidates[0]


def extract_managed_block(source_path: Path) -> str:
    """Extract the marked directives block (including markers) from the source template."""
    if not source_path.exists():
        raise FileNotFoundError(f"Source routing instructions template not found: {source_path}")

    content = source_path.read_text(encoding="utf-8")
    start_idx = content.find(START_MARKER)
    if start_idx == -1:
        raise ValueError(f"Source file {source_path} missing start marker: {START_MARKER}")

    end_idx = content.find(END_MARKER, start_idx)
    if end_idx == -1:
        raise ValueError(f"Source file {source_path} missing end marker: {END_MARKER}")

    end_idx += len(END_MARKER)
    return content[start_idx:end_idx].strip()


def install_directives(target_path: Path, source_path: Path) -> str:
    """Install or update the managed routing directives block in target_path."""
    block = extract_managed_block(source_path)

    target_path = Path(os.path.expanduser(str(target_path))).resolve()
    target_path.parent.mkdir(parents=True, exist_ok=True)

    if not target_path.exists():
        _atomic_write(target_path, block + "\n")
        return f"Created {target_path} with Personal Archive routing directives."

    current_text = target_path.read_text(encoding="utf-8")
    start_idx = current_text.find(START_MARKER)
    end_idx = current_text.find(END_MARKER)

    if start_idx != -1 and end_idx == -1:
        raise ValueError(
            f"Corrupted directives block in {target_path}: found start marker but missing end marker."
        )
    if start_idx == -1 and end_idx != -1:
        raise ValueError(
            f"Corrupted directives block in {target_path}: found end marker without start marker."
        )

    if start_idx != -1 and end_idx != -1:
        # Existing block found -> replace it
        end_idx += len(END_MARKER)
        before = current_text[:start_idx].strip()
        after = current_text[end_idx:].strip()

        new_parts = []
        if before:
            new_parts.append(before)
        new_parts.append(block)
        if after:
            new_parts.append(after)

        new_text = "\n\n".join(new_parts) + "\n"
        _atomic_write(target_path, new_text)
        return f"Updated Personal Archive routing directives in {target_path}."
    else:
        # No markers found -> append
        cleaned = current_text.strip()
        if cleaned:
            new_text = cleaned + "\n\n" + block + "\n"
        else:
            new_text = block + "\n"
        _atomic_write(target_path, new_text)
        return f"Appended Personal Archive routing directives to {target_path}."


def remove_directives(target_path: Path) -> str:
    """Remove the managed routing directives block from target_path."""
    target_path = Path(os.path.expanduser(str(target_path))).resolve()
    if not target_path.exists():
        return f"Target {target_path} does not exist. Nothing to remove."

    current_text = target_path.read_text(encoding="utf-8")
    start_idx = current_text.find(START_MARKER)
    end_idx = current_text.find(END_MARKER)

    if start_idx == -1 and end_idx == -1:
        return f"No Personal Archive routing directives found in {target_path}."
    if start_idx != -1 and end_idx == -1:
        raise ValueError(
            f"Corrupted directives block in {target_path}: found start marker but missing end marker."
        )
    if start_idx == -1 and end_idx != -1:
        raise ValueError(
            f"Corrupted directives block in {target_path}: found end marker without start marker."
        )

    end_idx += len(END_MARKER)
    before = current_text[:start_idx].strip()
    after = current_text[end_idx:].strip()

    new_parts = []
    if before:
        new_parts.append(before)
    if after:
        new_parts.append(after)

    if new_parts:
        new_text = "\n\n".join(new_parts) + "\n"
    else:
        new_text = ""

    _atomic_write(target_path, new_text)
    return f"Removed Personal Archive routing directives from {target_path}."


def check_directives(target_path: Path) -> bool:
    """Check if target_path contains the managed routing directives block."""
    target_path = Path(os.path.expanduser(str(target_path))).resolve()
    if not target_path.exists():
        return False
    text = target_path.read_text(encoding="utf-8")
    return (START_MARKER in text) and (END_MARKER in text) and ("archivist" in text)


def _atomic_write(path: Path, content: str):
    """Write content atomically to path via a sibling temporary file."""
    dir_name = path.parent
    dir_name.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", dir=dir_name, delete=False, encoding="utf-8") as tf:
        tf.write(content)
        temp_name = tf.name
    os.replace(temp_name, path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    install_parser = subparsers.add_parser("install", help="Install or update routing directives")
    install_parser.add_argument("--target", required=True, help="Path to target AGENTS.md")
    install_parser.add_argument(
        "--source",
        default=str(find_default_source()),
        help="Path to source template with directives block",
    )

    remove_parser = subparsers.add_parser("remove", help="Remove routing directives")
    remove_parser.add_argument("--target", required=True, help="Path to target AGENTS.md")

    check_parser = subparsers.add_parser("check", help="Check if routing directives are present")
    check_parser.add_argument("--target", required=True, help="Path to target AGENTS.md")

    args = parser.parse_args()

    try:
        if args.command == "install":
            msg = install_directives(Path(args.target), Path(args.source))
            print(msg)
            return 0
        elif args.command == "remove":
            msg = remove_directives(Path(args.target))
            print(msg)
            return 0
        elif args.command == "check":
            is_present = check_directives(Path(args.target))
            if is_present:
                print(f"Directives present in {args.target}")
                return 0
            else:
                print(f"Directives missing in {args.target}", file=sys.stderr)
                return 1
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
