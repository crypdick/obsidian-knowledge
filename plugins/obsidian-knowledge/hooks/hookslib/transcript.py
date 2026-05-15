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
