"""Shared retrieval + primer library for obsidian-knowledge plugin.

Imported by both the Claude Code adapter (hooks/recall-init.py) and the
Hermes Agent CLI memory provider (hermes-plugin/__init__.py).
"""

from lib.vault_index.config import VaultIndexConfig, load_config
from lib.vault_index.filters import apply_filters, score_path
from lib.vault_index.indexer import Indexer
from lib.vault_index.models import Hit
from lib.vault_index.primer import build_primer

__all__ = [
    "Hit",
    "Indexer",
    "VaultIndexConfig",
    "apply_filters",
    "build_primer",
    "load_config",
    "score_path",
]
