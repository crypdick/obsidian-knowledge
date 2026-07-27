"""Per-session bash-call counter for the reflect-nudge hook.

State lives at ~/.cache/obsidian-knowledge/<session-id>/bash-count
(integer in plain text). Counter is incremented on each PostToolUse
matching Bash; the hook fires its reminder every Nth invocation
(default N=100), continuously — no per-session suppression.
"""

from __future__ import annotations

from pathlib import Path

# NOTE: keep in sync with README.md § "reflect-nudge (PostToolUse on Bash)".
DEFAULT_THRESHOLD = 100


def increment(session_state_dir: Path) -> int:
    """Increment counter for this session; return the new value."""
    session_state_dir.mkdir(parents=True, exist_ok=True)
    counter_file = session_state_dir / "bash-count"
    if counter_file.exists():
        try:
            current = int(counter_file.read_text().strip())
        except (ValueError, OSError):
            current = 0
    else:
        current = 0
    new_value = current + 1
    counter_file.write_text(str(new_value))
    return new_value


def should_fire(count: int, threshold: int = DEFAULT_THRESHOLD) -> bool:
    """Return True if count is a positive multiple of threshold."""
    if count <= 0:
        return False
    return count % threshold == 0
