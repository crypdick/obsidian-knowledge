"""One semantic deadline, scaled by requested results and bounded by command time."""

from __future__ import annotations

import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

# NOTE: docs/CLI.md "Search health and network access" documents these values.
BASE_SECONDS = 5.0
SECONDS_PER_RESULT = 0.1
FALLBACK_RESERVE_SECONDS = 2.0
COMMAND_DEADLINE: ContextVar[float | None] = ContextVar("search_command_deadline", default=None)


@contextmanager
def command_deadline(seconds: int) -> Iterator[None]:
    """Carry the outer command's absolute deadline through initialization and queries."""
    token = COMMAND_DEADLINE.set(time.monotonic() + seconds if seconds > 0 else float("inf"))
    try:
        yield
    finally:
        COMMAND_DEADLINE.reset(token)


def semantic_deadline(top_k: int) -> float:
    """Allow fixed query overhead plus linear result work, reserving fallback time."""
    now = time.monotonic()
    outer = COMMAND_DEADLINE.get()
    if outer is None:
        try:
            ttl = int(os.environ.get("OBSIDIAN_KNOWLEDGE_SEARCH_TTL_SECONDS", "30"))
        except ValueError:
            ttl = 30
        outer = now + ttl if ttl > 0 else None
    budget = BASE_SECONDS + top_k * SECONDS_PER_RESULT
    if outer is not None:
        remaining = max(0.0, outer - now)
        budget = min(budget, remaining - min(FALLBACK_RESERVE_SECONDS, remaining / 2))
    return now + budget
