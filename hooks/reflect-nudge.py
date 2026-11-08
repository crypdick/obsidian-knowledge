#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""PostToolUse hook (matcher: Bash): continuous reflection nudge.

Fires every 100 bash invocations within a session. State lives at
~/.cache/obsidian-knowledge/<session-id>/bash-count. Continuous — no
per-session suppression. The continuous cadence is intentional: it
builds reflection into the agent's working rhythm, not a one-time
interruption.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hookslib import reflect_counter
from hookslib.stop_hook import read_input, session_state_key

REMINDER = (
    "Fix and verify bugs you introduce, failed validation of your changes, and defects "
    "needed to complete the user's request as part of the active task. Investigate unclear "
    "causes before calling them unrelated. For unrelated friction a future agent can avoid or "
    'the user can fix, use `obsidian-knowledge papercut "what happened"` and continue the task. '
    "Skip one-off transient failures, upstream bugs with no workaround, and harness limits. "
    "Follow the obsidian-knowledge skill's entry format. Routine debugging needs no entry; "
    "logging never replaces an in-scope fix."
)


def resolve_cache_root() -> Path:
    """~/.cache/obsidian-knowledge/, overridable via env for tests."""
    override = os.environ.get("OBSIDIAN_KNOWLEDGE_CACHE_ROOT")
    if override:
        return Path(override)
    return Path.home() / ".cache" / "obsidian-knowledge"


def main() -> int:
    payload = read_input()
    session_id = payload.get("session_id")
    if not session_id:
        return 0
    session_state_dir = resolve_cache_root() / session_state_key(session_id)
    try:
        count = reflect_counter.increment(session_state_dir)
    except OSError:
        # Optional reminder must not fail the tool call when state is unavailable.
        return 0

    if reflect_counter.should_fire(count):
        json.dump({"systemMessage": REMINDER}, sys.stdout)

    return 0


if __name__ == "__main__":
    sys.exit(main())
