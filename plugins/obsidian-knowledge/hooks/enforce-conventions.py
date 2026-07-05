#!/usr/bin/env python3
"""
PreToolUse hook: enforce vault conventions at write-time.

Three checks (run only on Write/Edit inside a configured vault):
- Wikilink .md extension: reject [[foo.md]], allow [[foo.jpg]].
- Dated-file naming: reject new files in Journal/*/diary/*/convos/*/plans/
  without a YYYY-MM-DD prefix (index.md exempt).
- Frontmatter YAML parse: reject malformed YAML in frontmatter blocks.

Shares regex/parser implementations with doctor.py and the
vault-organizer sweep via hooks/lib/patterns.py.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from hookslib.patterns import (
    DATE_PREFIX_RE,
    find_wikilink_ext_violations,
    is_in_dated_folder,
    parse_frontmatter,
)
from hookslib.vault_config import load_vault_roots
from hookslib.vault_policy import find_containing_vault


def deny(reason: str) -> None:
    json.dump(
        {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": f"BLOCKED [enforce-conventions]: {reason}",
            }
        },
        sys.stdout,
    )


def check_wikilink_ext(content: str) -> str | None:
    violations = find_wikilink_ext_violations(content)
    if not violations:
        return None
    lineno, match = violations[0]
    return (
        f"wikilink uses .md extension on line {lineno}: {match}. "
        f"Use [[foo]] instead of [[foo.md]] — Obsidian resolves by name."
    )


def check_dated_filename(tool_name: str, file_path: str, vault_root: str) -> str | None:
    if tool_name != "Write":
        return None
    try:
        rel = os.path.relpath(file_path, vault_root)
    except ValueError:
        rel = file_path
    if not is_in_dated_folder(rel):
        return None
    if os.path.exists(file_path):
        return None  # existing file — not a new creation
    basename = os.path.basename(file_path)
    if basename == "index.md":
        return None
    if DATE_PREFIX_RE.match(basename):
        return None
    return (
        f"File {basename} is in a dated folder but lacks a YYYY-MM-DD prefix. "
        f"Rename to e.g. '2026-04-21 {basename}' or '2026-04-21-{basename}'."
    )


def check_frontmatter(content: str) -> str | None:
    _, err = parse_frontmatter(content)
    if err is None:
        return None
    return f"malformed frontmatter: {err}"


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        sys.exit(0)

    tool_name = payload.get("tool_name", "")
    if tool_name not in ("Write", "Edit"):
        sys.exit(0)

    tool_input = payload.get("tool_input", {})
    file_path = tool_input.get("file_path", "")
    if not file_path:
        sys.exit(0)

    vault_root = find_containing_vault(file_path, load_vault_roots())
    if not vault_root:
        sys.exit(0)  # silent outside any configured vault

    # Write carries the full body in "content"; Edit carries it in "new_string".
    content = tool_input.get("content", "") if tool_name == "Write" else tool_input.get("new_string", "")

    for check in (
        lambda: check_wikilink_ext(content),
        lambda: check_dated_filename(tool_name, file_path, vault_root),
        lambda: check_frontmatter(content),
    ):
        reason = check()
        if reason:
            deny(reason)
            return


if __name__ == "__main__":
    main()
