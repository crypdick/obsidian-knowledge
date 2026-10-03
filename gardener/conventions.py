"""Shared write-time convention checks over visible vault Markdown."""

from __future__ import annotations

from pathlib import Path

from hookslib.patterns import (
    DATE_PREFIX_RE,
    PERIODIC_NOTE_RE,
    find_wikilink_ext_violations,
    is_in_dated_folder,
    parse_frontmatter,
)

from gardener.io import iter_markdown


def sweep(vault_root: Path) -> list[str]:
    issues: list[str] = []
    for md in iter_markdown(vault_root):
        rel = md.relative_to(vault_root)
        rel_str = str(rel)

        if is_in_dated_folder(rel_str):
            basename = md.name
            is_journal = rel_str.startswith("Journal/")
            if (
                basename != "index.md"
                and not DATE_PREFIX_RE.match(basename)
                and not (is_journal and PERIODIC_NOTE_RE.match(basename))
            ):
                issues.append(f"UNDATED_FILE\t{rel_str}")

        try:
            content = md.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        for lineno, match in find_wikilink_ext_violations(content):
            issues.append(f"WIKILINK_EXT\t{rel_str}:{lineno}\t{match}")

        _, err = parse_frontmatter(content)
        if err:
            # PyYAML errors span multiple lines (parser context block);
            # collapse to a single line so each issue stays grep-friendly.
            flat_err = " | ".join(part.strip() for part in err.splitlines() if part.strip())
            issues.append(f"YAML_ERR\t{rel_str}\t{flat_err}")

    return issues
