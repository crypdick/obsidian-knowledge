"""Shared retrieval + primer library for obsidian-knowledge plugin.

Imported by both the Claude Code adapter (hooks/recall-init.py) and the
Hermes Agent CLI memory provider (hermes-plugin/__init__.py).
"""
from lib.vault_index.config import VaultIndexConfig, load_config
from lib.vault_index.filters import apply_filters, score_path
from lib.vault_index.indexer import Hit, Indexer
from lib.vault_index.primer import build_primer

__all__ = [
    "VaultIndexConfig",
    "load_config",
    "apply_filters",
    "score_path",
    "Hit",
    "Indexer",
    "build_primer",
]
