"""Shared filename policy and Markdown checks over visible vault paths."""

from __future__ import annotations

from pathlib import Path

from hookslib.patterns import (
    dated_filename_violation,
    find_wikilink_ext_violations,
    parse_frontmatter,
)
from hookslib.vault_policy import load_vault_policy

from gardener.io import iter_paths


def sweep(vault_root: Path) -> list[str]:
    issues: list[str] = []
    policy = load_vault_policy()
    for path in iter_paths(vault_root):
        rel = path.relative_to(vault_root)
        rel_str = str(rel)

        # NOTE: docs/CLI.md, Vault maintenance, documents filename scope and policy.
        illegal = "".join(char for char in policy.illegal_filename_chars if char in path.name)
        if illegal:
            issues.append(f"ILLEGAL_FILENAME\t{rel_str}\tchars={illegal!r}")

        if not path.is_file() or path.suffix != ".md":
            continue

        if dated_filename_violation(rel_str):
            issues.append(f"UNDATED_FILE\t{rel_str}")

        try:
            content = path.read_text(encoding="utf-8", errors="replace")
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
