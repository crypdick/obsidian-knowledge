#!/usr/bin/env python3
"""PostToolUse hook (matcher: Bash): continuous reflection nudge.

Fires every 10 bash invocations within a session. State lives at
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

REMINDER = (
    "Step back: any insight worth saving to the knowledge base? "
    "If knowledge worth preserving, invoke the `remember-conversations` skill."
)


def resolve_cache_root() -> Path:
    """~/.cache/obsidian-knowledge/, overridable via env for tests."""
    override = os.environ.get("OBSIDIAN_KNOWLEDGE_CACHE_ROOT")
    if override:
        return Path(override)
    return Path.home() / ".cache" / "obsidian-knowledge"


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0

    session_id = payload.get("session_id", "unknown")
    session_state_dir = resolve_cache_root() / session_id

    count = reflect_counter.increment(session_state_dir)

    if reflect_counter.should_fire(count):
        json.dump({"systemMessage": REMINDER}, sys.stdout)

    return 0


if __name__ == "__main__":
    sys.exit(main())
