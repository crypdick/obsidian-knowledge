"""Helpers for reading session transcript JSONL files."""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any


def iter_tool_uses(transcript_path: str) -> Iterable[dict[str, Any]]:
    """Yield tool_use entries from a session transcript JSONL file.

    Each yielded dict has keys `id`, `name`, `input`.
    Missing files yield nothing. Malformed lines are skipped silently.
    """
    try:
        # opened outside the `with` so only the open() is guarded by this narrow
        # except; the file is still context-managed by `with f:` below.
        f = open(transcript_path, encoding="utf-8")  # noqa: SIM115
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
    back to their missing-transcript policy instead of treating missing data as inactivity.
    """
    if not transcript_path:
        return None
    try:
        # opened outside the `with` so only the open() is guarded by this narrow
        # except; the file is still context-managed by `with f:` below.
        f = open(transcript_path, encoding="utf-8")  # noqa: SIM115
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
            if _is_human_message(entry):
                n += 1
    return n


_INJECTED_PREFIXES = (
    "<hook_prompt",
    "<codex_internal_context",
    "# AGENTS.md instructions for ",
    "<environment_context>",
)


def _is_human_message(entry: Any) -> bool:
    if not isinstance(entry, dict) or entry.get("isMeta"):
        return False
    if entry.get("type") == "user":
        message = entry.get("message")
    elif entry.get("type") == "response_item":
        message = entry.get("payload")
        if not isinstance(message, dict) or message.get("role") != "user":
            return False
    else:
        # Codex event_msg records can mirror response_item messages.
        return False
    if not isinstance(message, dict):
        return False
    content = message.get("content")
    if isinstance(content, str):
        return bool(content.strip()) and not content.lstrip().startswith(_INJECTED_PREFIXES)
    if not isinstance(content, list):
        return False
    if any(isinstance(block, dict) and block.get("type") == "tool_result" for block in content):
        return False
    return any(
        isinstance(block, dict)
        and (
            block.get("type") in {"image", "input_image", "input_audio"}
            or (
                isinstance(block.get("text"), str)
                and bool(block["text"].strip())
                and not block["text"].lstrip().startswith(_INJECTED_PREFIXES)
            )
        )
        for block in content
    )
