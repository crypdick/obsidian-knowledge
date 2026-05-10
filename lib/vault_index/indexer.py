"""Vault indexer — builds and queries the path index.

Stub — implementation deferred to a later task.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from lib.vault_index.config import VaultIndexConfig


@dataclass
class Hit:
    path: str
    score: float


class Indexer:
    """Indexes vault paths and retrieves ranked hits."""

    def __init__(self, vault_root: Path, config: VaultIndexConfig) -> None:
        raise NotImplementedError
