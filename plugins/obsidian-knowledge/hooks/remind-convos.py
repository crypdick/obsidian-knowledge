#!/usr/bin/env python3
"""Stop hook: remind the agent to file valuable conversations as vault notes.

Vault detection: cwd must be inside a configured vault root from
~/.config/obsidian-knowledge/vaults.yaml. Replaces the older walk-up
heuristic, which fired on any `.obsidian/` directory the agent
happened to be inside — even ones outside the user's allowlist.

Cooldown: at most one block per session per 5 minutes, tracked via
a /tmp marker file's mtime.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hookslib.stop_hook import emit_block, in_cooldown, read_input
from hookslib.vault_config import matching_vault_root


def build_reason(vault_root: str) -> str:
    """Build the preserve-your-work reminder with vault-root-anchored paths.

    The changelog (option 1) lives under `Utility/obsidian-knowledge/`, while
    notes (options 2-5) live under `wiki/`. Emitting the changelog's absolute
    path and separating the two destinations prevents agents from conflating
    the "file these in wiki/" note guidance into writing the changelog to
    `wiki/Utility/obsidian-knowledge/`.
    """
    changelog_dir = os.path.join(vault_root, "Utility", "obsidian-knowledge", "changelog")
    return (
        "Reminder: before wrapping up, consider what's worth preserving from this "
        "session. Options: (1) Changelog entry — always, if anything substantive "
        f"happened: create {changelog_dir}/YYYY-MM-DD-HHMMSS-<slug>.md "
        "(canonical location — never under wiki/), "
        "one terse line per action ('YYYY-MM-DD HH:MM — what happened [→ [[wikilink]]]'). "
        "(2) Learning page — if the session was Q&A or you explained "
        "a concept. Default for educational exchanges. Route by topic: consult "
        "the wiki's top-level index and a vault search to pick the subtree where "
        "neighboring notes already live; a dedicated learning subtree is the "
        "fallback when no better home exists. Accrete into the existing concept "
        "page or create one. (3) Diary note — if you worked through a process, "
        "incident, or debugging session worth narrating. (4) Convo note — if you "
        "produced analysis, comparisons, or decision rationales. (5) Guide — if "
        "you discovered a procedure others would need to repeat. Think especially "
        "about gotchas for future maintainers — tricky configurations, non-obvious "
        "failure modes, things that cost time to figure out. Notes (2)-(5) — not "
        "the changelog — go in the vault's wiki/ tree, NOT in "
        "~/.claude/projects/.../memory/. The "
        "auto-memory directory is deprecated; knowledge belongs in the wiki, "
        "behavior rules belong in CLAUDE.md. Use `obsidian-knowledge search` to "
        "find relevant existing notes before filing. Use the remember-conversations "
        "skill to file. If nothing worth preserving or you already filed, "
        "carry on."
    )


def main() -> None:
    vault_root = matching_vault_root(os.getcwd())
    if vault_root is None:
        sys.exit(0)
    payload = read_input()
    if in_cooldown(payload, marker_basename="convos"):
        sys.exit(0)
    emit_block(build_reason(vault_root))


if __name__ == "__main__":
    main()
