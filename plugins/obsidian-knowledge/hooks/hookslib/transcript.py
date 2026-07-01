"""Helpers for reading session transcript JSONL files."""

from __future__ import annotations

import json
from typing import Iterable


def iter_tool_uses(transcript_path: str) -> Iterable[dict]:
    """Yield tool_use entries from a session transcript JSONL file.

    Each yielded dict has keys `id`, `name`, `input`.
    Missing files yield nothing. Malformed lines are skipped silently.
    """
    try:
        f = open(transcript_path, encoding="utf-8")
    except FileNotFoundError:
        return
    with f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            msg = entry.get("message") or {}
            content = msg.get("content")
            if not isinstance(content, list):
                continue
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    yield {
                        "id": block.get("id"),
                        "name": block.get("name"),
                        "input": block.get("input") or {},
                    }


def count_user_messages(transcript_path: str | None) -> int | None:
    """Count genuine user messages in a session transcript.

    "Genuine" excludes tool-result carriers (user-role entries whose content is
    a list containing a `tool_result` block) and meta entries, so the count
    only advances when the human actually sends something. Used to gate
    SessionStart re-injection on real activity: a compaction loop produces many
    SessionStart events with no new user message, so the count stays flat.

    Returns None when the path is missing or unreadable, so callers can fall
    back to a time-only debounce instead of treating "no data" as "no activity".
    """
    if not transcript_path:
        return None
    try:
        f = open(transcript_path, encoding="utf-8")
    except OSError:
        return None
    n = 0
    with f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if entry.get("type") != "user" or entry.get("isMeta"):
                continue
            content = (entry.get("message") or {}).get("content")
            if isinstance(content, str):
                n += 1
            elif isinstance(content, list) and not any(
                isinstance(b, dict) and b.get("type") == "tool_result" for b in content
            ):
                n += 1
    return n
