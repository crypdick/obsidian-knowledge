"""Shared vault-index data models.

Kept dependency-light (pydantic only) so both indexer.py and filters.py can
import `Hit` at runtime without an import cycle. beartype resolves forward
references from a module's runtime namespace, so `Hit` must be importable here
rather than only under TYPE_CHECKING.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class IndexBusyError(RuntimeError):
    """Raised when another process is using this vault index."""


class Hit(BaseModel):
    path: str
    score: float
    weight_applied: float = 1.0
    snippet: str = ""


class SearchReport(BaseModel):
    """Hits and the retrieval mode used for one query."""

    # NOTE: docs/CLI.md "JSON search output" defines this stdout contract.
    mode: Literal["keyword", "hybrid"]
    degraded_reason: str | None
    hits: list[Hit]
