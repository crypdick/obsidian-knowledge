#!/usr/bin/env python3
"""
SessionStart hook: the vault doctor.

Runs once at session start when cwd is inside a configured vault.
Two passes:
- Pass A: count `- [ ]` entries in .config/obsidian-knowledge/NEEDS_ATTENTION.md
- Pass B: walk the vault (skip dotfolders and _sources/) and count
  convention violations using the shared patterns module

Prints a one-line digest if any count is > 0, else silent.

Read-only — never writes to NEEDS_ATTENTION.md. Vault-organizer is
the sole writer; run it to persist findings.
"""

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib.patterns import (  # noqa: E402
    DATE_PREFIX_RE,
    find_wikilink_ext_violations,
    is_in_dated_folder,
    parse_frontmatter,
)
from lib.vault_config import load_vault_roots  # noqa: E402
from lib.vault_policy import find_containing_vault  # noqa: E402

SKIP_DIRS = {".obsidian", ".config", ".git", ".trash", ".claude", "_sources"}


def count_needs_attention(vault_root: str) -> int:
    path = os.path.join(vault_root, ".config", "obsidian-knowledge", "NEEDS_ATTENTION.md")
    if not os.path.exists(path):
        return 0
    with open(path, encoding="utf-8") as f:
        content = f.read()
    return len(re.findall(r"^- \[ \]", content, re.MULTILINE))


def iter_vault_md_files(vault_root: str):
    for root, dirs, files in os.walk(vault_root):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
        for name in files:
            if name.endswith(".md"):
                yield os.path.join(root, name)


def scan_vault(vault_root: str) -> dict[str, int]:
    wikilink_ext = 0
    undated = 0
    yaml_err = 0
    for path in iter_vault_md_files(vault_root):
        rel = os.path.relpath(path, vault_root)
        if is_in_dated_folder(rel):
            basename = os.path.basename(rel)
            if basename != "index.md" and not DATE_PREFIX_RE.match(basename):
                undated += 1
        try:
            with open(path, encoding="utf-8") as f:
                content = f.read()
        except (OSError, UnicodeDecodeError):
            continue
        if find_wikilink_ext_violations(content):
            wikilink_ext += 1
        _, err = parse_frontmatter(content)
        if err:
            yaml_err += 1
    return {
        "wikilink-ext": wikilink_ext,
        "undated-file": undated,
        "yaml-err": yaml_err,
    }


def main() -> None:
    try:
        sys.stdin.read()
    except Exception:
        pass

    vault_root = find_containing_vault(os.getcwd(), load_vault_roots())
    if not vault_root:
        sys.exit(0)

    needs_attention = count_needs_attention(vault_root)
    scan = scan_vault(vault_root)
    total = needs_attention + sum(scan.values())
    if total == 0:
        sys.exit(0)

    parts = [f"{needs_attention} needs-attention"]
    parts += [f"{v} {k}" for k, v in scan.items()]
    digest = "vault: " + " + ".join(parts) + " — run vault-organizer to review"
    print(digest)


if __name__ == "__main__":
    main()
