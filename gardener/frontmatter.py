"""Repair stray stacked frontmatter markers; real second blocks require manual review."""

from __future__ import annotations

import argparse
from pathlib import Path

from gardener.io import OrganizerPolicy, resolve_vault, write_checked

FRONTMATTER_SCAN_LIMIT = 60


def find_stacked_region(lines: list[str]) -> tuple[list[int], list[int]] | None:
    """Find stacked frontmatter markers after the real frontmatter close.

    Real frontmatter is the first `---...---` block. After it, walk forward
    skipping blanks. Collect any further standalone `---` lines and the
    *content lines* between them. Stop when we hit a non-frontmatter
    content line (a line that isn't `---` and isn't blank).

    Returns (extra_marker_indices, extra_content_indices). Both empty lists
    means no issue. Extra content lines indicate a real second block that
    needs manual merge.
    """
    if not lines or lines[0] != "---":
        return None

    first_close = next(
        (i for i in range(1, min(len(lines), FRONTMATTER_SCAN_LIMIT)) if lines[i] == "---"),
        None,
    )
    if first_close is None:
        return None

    extra_markers: list[int] = []
    extra_content: list[int] = []
    j = first_close + 1
    saw_marker_after_blank = False

    while j < min(len(lines), FRONTMATTER_SCAN_LIMIT):
        line = lines[j]
        stripped = line.strip()

        if stripped == "":
            j += 1
            continue

        if line == "---":
            extra_markers.append(j)
            saw_marker_after_blank = True
            j += 1
            continue

        if saw_marker_after_blank:
            # Inside a stray/second block: collect until we hit body content.
            # Heuristic: YAML key lines look like `key:` or `key: value` or
            # `- list-item`. Body usually starts with `#`, `*`, **bold**, etc.
            if line.startswith(("#", "*", ">", "|", "[")):
                break
            extra_content.append(j)
            j += 1
            continue

        break

    if not extra_markers:
        return None

    return (extra_markers, extra_content)


def fix_file(vault: Path, relative: str, write: bool) -> str:
    """Return one of: 'OK', 'STRAY_FIXED', 'STRAY_DRY', 'NEEDS_MERGE'."""
    path = OrganizerPolicy.load(vault).writable(vault, relative)
    text = path.read_bytes().decode("utf-8")
    newline = "\r\n" if "\r\n" in text else "\n"
    lines = text.split(newline)

    region = find_stacked_region(lines)
    if region is None:
        return "OK"

    extra_markers, extra_content = region

    if extra_content:
        return "NEEDS_MERGE"

    drop = set(extra_markers)
    new_lines = [line for i, line in enumerate(lines) if i not in drop]

    if not write:
        return "STRAY_DRY"

    write_checked(vault, relative, text, newline.join(new_lines))
    return "STRAY_FIXED"


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Preview or repair stray stacked frontmatter markers")
    parser.add_argument("--vault", type=Path, help="default: configured vault")
    parser.add_argument("--apply", action="store_true", help="apply reviewed marker repairs")
    parser.add_argument("paths", nargs="+", help="vault-relative Markdown paths")
    args = parser.parse_args(argv)
    vault = resolve_vault(args.vault)
    needs_merge = False
    for relative in args.paths:
        if Path(relative).suffix != ".md":
            raise ValueError("frontmatter only edits Markdown files")
        result = fix_file(vault, relative, args.apply)
        if result == "NEEDS_MERGE":
            needs_merge = True
            print(f"NEEDS_MERGE\t{relative}")
        elif result == "STRAY_FIXED":
            print(f"FIXED\t{relative}")
        elif result == "STRAY_DRY":
            print(f"WOULD_FIX\t{relative}")
    if needs_merge:
        parser.exit(1, "Real second frontmatter block: merge keys manually.\n")
