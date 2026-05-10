"""Vault indexer — builds and queries the path index.

Stub — implementation deferred to a later task (Task 8).
"""
from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel

from lib.vault_index.config import VaultIndexConfig


class Hit(BaseModel):
    path: str
    score: float
    weight_applied: float = 1.0


class Indexer:
    """Indexes vault paths and retrieves ranked hits."""

    def __init__(self, vault_root: Path, config: VaultIndexConfig) -> None:
        raise NotImplementedError
