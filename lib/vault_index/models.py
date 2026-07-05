"""Shared vault-index data models.

Kept dependency-light (pydantic only) so both indexer.py and filters.py can
import `Hit` at runtime without an import cycle. beartype resolves forward
references from a module's runtime namespace, so `Hit` must be importable here
rather than only under TYPE_CHECKING.
"""

from __future__ import annotations

from pydantic import BaseModel


class Hit(BaseModel):
    path: str
    score: float
    weight_applied: float = 1.0
