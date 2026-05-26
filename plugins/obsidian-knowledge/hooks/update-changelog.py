#!/usr/bin/env python3
"""Stop hook: remind the agent to update CHANGELOG.md in the vault.

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
    "Reminder: if this session produced anything valuable for future agents to "
    "know (edits, decisions, discoveries, context, dead ends), create a new file "
    "in Utility/obsidian-knowledge/changelog/ named YYYY-MM-DD-HHMMSS-<slug>.md "
    "(e.g. 2026-05-12-143022-vault-organizer.md). "
    "Write one terse line per significant action: "
    "'YYYY-MM-DD HH:MM — <what happened> [→ [[wikilink]] if diary/convo filed]'. "
    "No narrative, no code blocks — pointers only. "
    "Immediately add that new file to Utility/obsidian-knowledge/changelog/index.md "
    "as '- [[YYYY-MM-DD-HHMMSS-slug]] — short orientation phrase' so it is not "
    "left as an orphan for vault-gardener. "
    "If nothing substantive happened or you already logged and indexed it, carry on."
)


def main() -> None:
    if not is_in_vault(os.getcwd()):
        sys.exit(0)
    payload = read_input()
    if in_cooldown(payload, marker_basename="changelog"):
        sys.exit(0)
    emit_block(REASON)


if __name__ == "__main__":
    main()
