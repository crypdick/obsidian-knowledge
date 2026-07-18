"""Shared scaffolding for Stop hooks.

Each Stop hook reads a JSON payload from stdin (session_id,
stop_hook_active), debounces repeated invocations, and emits a
`{"decision": "block", "reason": ...}` JSON block — or exits silently to
allow the conversation to continue normally.
"""

import hashlib
import json
import os
import sys
import tempfile
import time
from typing import Any

from .transcript import count_user_messages


def read_input() -> dict[str, Any]:
    """Read and parse the JSON payload from stdin. Returns {} on parse error."""
    try:
        payload: dict[str, Any] = json.load(sys.stdin)
        return payload
    except (json.JSONDecodeError, ValueError):
        return {}


def _marker_cooldown(session_id, marker_basename: str, cooldown_seconds: int) -> bool:
    """Per-session cooldown gate backed by a /tmp marker file's mtime.

    Returns True (skip) if the marker was touched less than `cooldown_seconds`
    ago. Otherwise touches (creates) the marker to start the next window and
    returns False. A missing `session_id` means no per-session marker is
    possible, so this returns False (don't skip).
    """
    if not session_id:
        return False
    marker = f"/tmp/.obsidian-hook-{marker_basename}-{session_id}"
    now = time.time()
    if os.path.exists(marker) and now - os.path.getmtime(marker) < cooldown_seconds:
        return True
    # Touch (create) the marker to start the next cooldown window.
    with open(marker, "w"):
        pass
    return False


def in_cooldown(payload: dict[str, Any], marker_basename: str, cooldown_seconds: int = 300) -> bool:
    """Return True if this hook should skip emitting a block.

    Skips when:
    - `stop_hook_active` is True (Claude is continuing past a prior block).
    - The cooldown marker was touched less than `cooldown_seconds` ago.

    On a non-skip outcome the marker is touched (or created) so the next
    invocation within `cooldown_seconds` will skip.
    """
    if payload.get("stop_hook_active"):
        return True
    return _marker_cooldown(payload.get("session_id"), marker_basename, cooldown_seconds)


def capture_debounce(
    payload: dict[str, Any],
    marker_basename: str = "capture-session",
    cooldown_seconds: int = 300,
) -> bool:
    """Atomically allow one capture decision per user-message generation.

    Codex and Claude Stop hooks may be invoked in parallel (including by old
    cached manifests that still launch both legacy capture aliases). When the
    transcript is available, key the claim by a hash of ``session_id`` plus the
    genuine user-message count. The same finalization generation therefore
    emits exactly once regardless of elapsed time, while a later user message
    can produce a new decision. When transcript data is unavailable, retain the
    time-based cooldown used by older runtimes such as Hermes.
    """
    if payload.get("stop_hook_active"):
        return True

    session_id = payload.get("session_id")
    user_message_count = count_user_messages(payload.get("transcript_path"))
    if not session_id or user_message_count in (None, 0):
        return _atomic_cooldown_claim(session_id, marker_basename, cooldown_seconds)

    session_digest = hashlib.sha256(str(session_id).encode()).hexdigest()[:24]
    marker = os.path.join(
        tempfile.gettempdir(),
        f".obsidian-hook-{marker_basename}-{session_digest}-user-{user_message_count}",
    )
    try:
        fd = os.open(marker, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        return True
    except OSError:
        return _atomic_cooldown_claim(session_id, marker_basename, cooldown_seconds)
    os.close(fd)
    return False


def _atomic_cooldown_claim(session_id: str | None, marker_basename: str, cooldown_seconds: int) -> bool:
    """Atomically claim the current cooldown bucket; return True if claimed."""
    if not session_id:
        return False
    session_digest = hashlib.sha256(str(session_id).encode()).hexdigest()[:24]
    bucket = int(time.time() // max(1, cooldown_seconds))
    marker = os.path.join(
        tempfile.gettempdir(),
        f".obsidian-hook-{marker_basename}-{session_digest}-bucket-{bucket}",
    )
    try:
        fd = os.open(marker, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        return True
    except OSError:
        # Capture is optional. If the claim cannot be made safely, suppress the
        # reminder instead of risking duplicate Stop continuations.
        return True
    os.close(fd)
    return False


SESSIONSTART_COOLDOWN_S = 300  # 5 minutes


def session_debounce(
    payload: dict[str, Any],
    marker_basename: str,
    cooldown_seconds: int = SESSIONSTART_COOLDOWN_S,
) -> bool:
    """Return True if a SessionStart hook should skip (already ran recently).

    SessionStart fires on startup|resume|compact with no built-in dedup, so a
    rapid re-fire re-runs the hook back to back. The worst case is an
    auto-compaction loop: injecting context right after a compaction can push
    the window back over the threshold, triggering another compaction and
    another SessionStart.

    Re-running is allowed only when BOTH gates open:
    - Time: at least `cooldown_seconds` (default 5 min) since the last run.
    - Activity: the user has sent a new message since the last run. A
      compaction loop emits many SessionStart events with no new user message,
      so this gate alone stops the storm no matter how long it drags on. Falls
      back to time-only when the transcript is unavailable (count is None).

    The session_id is stable across a session's compact/resume events, so the
    marker (which stores the user-message count seen at the last run) keys the
    whole thing per session.
    """
    session_id = payload.get("session_id")
    if not session_id:
        # No session id → can't key a per-session marker. Don't skip.
        return False

    msg_count = count_user_messages(payload.get("transcript_path"))
    marker = f"/tmp/.obsidian-hook-{marker_basename}-{session_id}"
    now = time.time()

    if os.path.exists(marker):
        within_cooldown = now - os.path.getmtime(marker) < cooldown_seconds
        no_new_message = False
        if msg_count is not None:
            try:
                last_count = int((_read_marker(marker) or "").strip())
            except ValueError:
                last_count = None
            no_new_message = last_count is not None and msg_count <= last_count
        if within_cooldown or no_new_message:
            return True

    # Arm: record the current message count and reset the cooldown window.
    with open(marker, "w") as fh:
        fh.write("" if msg_count is None else str(msg_count))
    return False


def _read_marker(path: str) -> str:
    """Return the marker file's contents, or '' if unreadable."""
    try:
        with open(path) as fh:
            return fh.read()
    except OSError:
        return ""


def emit_block(reason: str) -> None:
    """Print a `{"decision": "block", "reason": ...}` JSON block on stdout."""
    json.dump({"decision": "block", "reason": reason}, sys.stdout)
