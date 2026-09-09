"""Shared retrieval + primer library for obsidian-knowledge plugin.

Imported by both the Claude Code adapter (hooks/recall-init.py) and the
Hermes Agent CLI memory provider (hermes-plugin/__init__.py).
"""

from typing import TYPE_CHECKING, Any

from lib.vault_index.config import VaultIndexConfig, load_config
from lib.vault_index.filters import apply_filters, score_path
from lib.vault_index.models import Hit
from lib.vault_index.primer import build_primer

if TYPE_CHECKING:
    from lib.vault_index.indexer import Indexer


def __getattr__(name: str) -> Any:
    # File I/O, hook dispatch, and --help must not load the retrieval stack.
    if name == "Indexer":
        from lib.vault_index.indexer import Indexer

        return Indexer
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "Hit",
    "Indexer",
    "VaultIndexConfig",
    "apply_filters",
    "build_primer",
    "load_config",
    "score_path",
]
