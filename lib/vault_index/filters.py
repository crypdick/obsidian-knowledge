"""Filter and scoring functions for vault_index paths.

Stub — implementation deferred to a later task.
"""
from __future__ import annotations

from lib.vault_index.config import IndexFilter, DigestFilter


def apply_filters(path: str, filter_cfg: IndexFilter | DigestFilter) -> bool:
    """Return True if *path* passes the allow/deny regex rules."""
    raise NotImplementedError


def score_path(path: str, weights: list) -> float:
    """Return a weighted relevance score for *path*."""
    raise NotImplementedError
