"""Shared scaffolding for Stop hooks.

Each Stop hook reads a JSON payload from stdin (session_id,
stop_hook_active), enforces a per-session cooldown via a marker file's
mtime, and emits a `{"decision": "block", "reason": ...}` JSON block —
or exits silently to allow the conversation to continue normally.
"""
import json
import os
import sys
import time


def read_input() -> dict:
    """Read and parse the JSON payload from stdin. Returns {} on parse error."""
    try:
        return json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return {}


def in_cooldown(payload: dict, marker_basename: str, cooldown_seconds: int = 300) -> bool:
    """Return True if this hook should skip emitting a block.

    Skips when:
    - `stop_hook_active` is True (Claude is continuing past a prior block).
    - The cooldown marker was touched less than `cooldown_seconds` ago.

    On a non-skip outcome the marker is touched (or created) so the next
    invocation within `cooldown_seconds` will skip.
    """
    if payload.get("stop_hook_active"):
        return True
    session_id = payload.get("session_id")
    if not session_id:
        # No session id → can't apply per-session cooldown. Don't skip.
        return False
    marker = f"/tmp/.obsidian-hook-{marker_basename}-{session_id}"
    now = time.time()
    if os.path.exists(marker) and now - os.path.getmtime(marker) < cooldown_seconds:
        return True
    # Touch (create) the marker to start the next cooldown window.
    with open(marker, "w"):
        pass
    return False


def emit_block(reason: str) -> None:
    """Print a `{"decision": "block", "reason": ...}` JSON block on stdout."""
    json.dump({"decision": "block", "reason": reason}, sys.stdout)
