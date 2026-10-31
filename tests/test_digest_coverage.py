"""Digest notes stay findable while other notes dominate keyword matches or indexing."""

from __future__ import annotations

import asyncio
from pathlib import Path

from lib.vault_index.config import DigestFilter, VaultIndexConfig
from lib.vault_index.indexer import Indexer

CONFIG = VaultIndexConfig(digest=DigestFilter(allow_regex=["^wiki/"]))


def make_vault(root: Path) -> Path:
    vault = root / "vault"
    (vault / "Utility").mkdir(parents=True)
    (vault / "wiki").mkdir()
    for number in range(200):
        (vault / f"Utility/run{number:03}.md").write_text(
            f"# Run {number}\n\nworkaround workaround workaround\n"
        )
    (vault / "wiki/fix.md").write_text(
        "# Fix\n\nThe documented workaround for the sync bug, explained at length.\n"
    )
    return vault


def test_keyword_search_finds_digest_note_crowded_out_by_other_matches(tmp_path):
    vault = make_vault(tmp_path)
    instance = Indexer(vault, tmp_path / "cache", CONFIG, vector_enabled=False)
    try:
        instance.full_reindex()
        report = instance.search_report("workaround")
        everything = instance.search_report("workaround", override_digest_filter=True)
    finally:
        asyncio.run(instance._store.close())
    assert report.mode == "keyword"
    assert [hit.path for hit in report.hits] == ["wiki/fix.md"]
    assert len(everything.hits) == CONFIG.top_k


def test_rebuild_embeds_digest_notes_first(tmp_path, fake_ollama):
    vault = make_vault(tmp_path)
    instance = Indexer(vault, tmp_path / "cache", CONFIG)
    try:
        instance.full_reindex()
    finally:
        asyncio.run(instance._store.close())
    assert "documented workaround" in fake_ollama.texts[0]
