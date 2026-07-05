#!/usr/bin/env python3
"""fix-stacked-frontmatter: detect and auto-fix stray duplicate `---` markers.

The most common cause of STACKED_FRONTMATTER is a stray duplicate `---` line
right after a normal frontmatter close — typically left by a Templater
template or merge artifact. This script collapses those automatically.

True two-block merges (where the second `---...---` block contains real keys)
are left alone and reported for manual review, since merging may need
human judgment about which keys win.

Usage:
  python3 fix-stacked-frontmatter.py <file> [<file>...]            # dry run
  python3 fix-stacked-frontmatter.py --fix <file> [<file>...]      # rewrite

Exit 0 if no issues or all fixed; exit 1 if files need manual merge.
"""

from __future__ import annotations

import sys
from pathlib import Path

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
            if (
                line.startswith("#")
                or line.startswith("*")
                or line.startswith(">")
                or line.startswith("|")
                or line.startswith("[")
            ):
                break
            extra_content.append(j)
            j += 1
            continue

        break

    if not extra_markers:
        return None

    return (extra_markers, extra_content)


def fix_file(path: Path, write: bool) -> str:
    """Return one of: 'OK', 'STRAY_FIXED', 'STRAY_DRY', 'NEEDS_MERGE'."""
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.split("\n")

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

    path.write_text("\n".join(new_lines), encoding="utf-8")
    return "STRAY_FIXED"


def main() -> None:
    args = sys.argv[1:]
    write = False
    if args and args[0] == "--fix":
        write = True
        args = args[1:]

    if not args:
        print("Usage: fix-stacked-frontmatter.py [--fix] <file> [<file>...]", file=sys.stderr)
        sys.exit(2)

    needs_merge = []
    fixed = []
    stray = []

    for arg in args:
        path = Path(arg)
        if not path.is_file():
            print(f"SKIP: {path} (not a file)", file=sys.stderr)
            continue
        result = fix_file(path, write)
        if result == "NEEDS_MERGE":
            needs_merge.append(path)
            print(f"NEEDS_MERGE\t{path}")
        elif result == "STRAY_FIXED":
            fixed.append(path)
            print(f"FIXED\t{path}")
        elif result == "STRAY_DRY":
            stray.append(path)
            print(f"WOULD_FIX\t{path}")

    if needs_merge:
        print(
            f"\n{len(needs_merge)} file(s) have a real second frontmatter block — "
            "merge keys manually per lib/stacked-frontmatter.md.",
            file=sys.stderr,
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
