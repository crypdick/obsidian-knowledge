"""Report possible stacked frontmatter without guessing author intent."""

from __future__ import annotations

import argparse
from pathlib import Path

from note_frontmatter import frontmatter_envelope

from gardener.io import OrganizerPolicy, resolve_vault

FRONTMATTER_SCAN_LIMIT = 60


def stacked_marker(text: str) -> bool:
    """Recognize possible second blocks; thematic breaks have identical syntax."""
    limited = "".join(text.splitlines(keepends=True)[:FRONTMATTER_SCAN_LIMIT])
    try:
        envelope = frontmatter_envelope(limited)
    except ValueError:
        return False
    if envelope is None:
        return False
    body = limited[envelope.end() :].lstrip("\r\n \t")
    return body.splitlines()[:1] == ["---"]


def fix_file(vault: Path, relative: str, write: bool) -> str:
    """Report OK or NEEDS_MERGE; even --apply cannot resolve ambiguous syntax."""
    path = OrganizerPolicy.load().writable(vault, relative)
    text = path.read_bytes().decode("utf-8")
    # NOTE: docs/CLI.md and skills/vault-organizer/lib/stacked-frontmatter.md
    # explain why automatic marker deletion is no longer safe.
    return "NEEDS_MERGE" if stacked_marker(text) else "OK"


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vault", type=Path, help="default: configured vault")
    parser.add_argument(
        "--apply", action="store_true", help="accepted for compatibility; never deletes markers"
    )
    parser.add_argument("paths", nargs="+", help="vault-relative Markdown paths")
    args = parser.parse_args(argv)
    vault = resolve_vault(args.vault)
    needs_merge = False
    for relative in args.paths:
        if Path(relative).suffix != ".md":
            raise ValueError("frontmatter only edits Markdown files")
        if fix_file(vault, relative, args.apply) == "NEEDS_MERGE":
            needs_merge = True
            print(f"NEEDS_MERGE\t{relative}")
    if needs_merge:
        parser.exit(1, "Possible stacked frontmatter or thematic break: review manually; no changes made.\n")
