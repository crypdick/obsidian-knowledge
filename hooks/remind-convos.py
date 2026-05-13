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
from hookslib.stop_hook import emit_block, in_cooldown, read_input  # noqa: E402
from hookslib.vault_config import is_in_vault  # noqa: E402


REASON = (
    "Reminder: before wrapping up, consider what's worth preserving from this "
    "session. Options: (1) Changelog entry — always, if anything substantive "
    "happened: create Utility/obsidian-knowledge/changelog/YYYY-MM-DD-HHMMSS-<slug>.md, "
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
    "failure modes, things that cost time to figure out. File these in the "
    "vault's wiki/ tree — NOT in ~/.claude/projects/.../memory/. The "
    "auto-memory directory is deprecated; knowledge belongs in the wiki, "
    "behavior rules belong in CLAUDE.md. Use `obsidian-knowledge search` to "
    "find relevant existing notes before filing. Use the remember-conversations "
    "skill to file. If nothing worth preserving or you already filed, "
    "carry on."
)


def main() -> None:
    if not is_in_vault(os.getcwd()):
        sys.exit(0)
    payload = read_input()
    if in_cooldown(payload, marker_basename="convos"):
        sys.exit(0)
    emit_block(REASON)


if __name__ == "__main__":
    main()
