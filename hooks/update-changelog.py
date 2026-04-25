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
from lib.stop_hook import emit_block, in_cooldown, read_input  # noqa: E402
from lib.vault_config import is_in_vault  # noqa: E402


REASON = (
    "Reminder: if this session produced anything valuable for future agents to "
    "know (edits, decisions, discoveries, context, dead ends), append a dated "
    "entry to CHANGELOG.md. If nothing substantive happened or you already "
    "logged, carry on."
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
