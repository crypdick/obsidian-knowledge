"""Sync completion must describe persisted index state, including contention."""

from __future__ import annotations

import asyncio
import subprocess
import sys
from pathlib import Path

import pytest

import hermes_plugin
from lib.vault_index.config import VaultIndexConfig
from lib.vault_index.indexer import Indexer, default_cache_dir, index_lock


def test_busy_sync_does_not_publish_freshness_or_skip_retry(tmp_path: Path, monkeypatch):
    vault = tmp_path / "vault"
    (vault / "wiki").mkdir(parents=True)
    (vault / "wiki/old.md").write_text("original information")
    monkeypatch.setenv("OBSIDIAN_KNOWLEDGE_CACHE_ROOT", str(tmp_path / "cache"))
    monkeypatch.setenv("MEMWEAVE_EMBEDDING_API_BASE", "http://127.0.0.1:1")
    cache = default_cache_dir(vault)
    indexer = Indexer(vault, cache, VaultIndexConfig(), vector_enabled=False)
    root = str(Path(__file__).parents[1])
    try:
        indexer.full_reindex()
        (vault / "wiki/new.md").write_text("new information")
        with index_lock(cache, exclusive=True):
            with pytest.raises(subprocess.CalledProcessError):
                hermes_plugin._run_vault_sync(str(vault), root, [sys.executable])
        assert not (cache / "last-sync-fingerprint.txt").exists()

        hermes_plugin._run_vault_sync(str(vault), root, [sys.executable])
        assert sorted(indexer.indexed_paths()) == ["wiki/new.md", "wiki/old.md"]
    finally:
        asyncio.run(indexer._store.close())


def test_failed_background_sync_is_retried_on_next_turn(tmp_path, monkeypatch):
    monkeypatch.setenv("OBSIDIAN_VAULT_ROOT", str(tmp_path))
    provider = hermes_plugin.ObsidianKnowledgeProvider()
    provider.initialize("retry-sync")
    calls = []

    def sync(*args):
        calls.append(args)
        if len(calls) == 1:
            raise subprocess.CalledProcessError(1, ["sync"])

    monkeypatch.setattr(hermes_plugin, "_run_vault_sync", sync)
    hermes_plugin._on_post_tool_call(
        tool_name="write_file",
        args={"path": str(tmp_path / "note.md")},
        session_id="retry-sync",
        result='{"bytes_written": 10}',
    )
    for _ in range(2):
        provider.sync_turn("", "")
        provider._sync_thread.join(timeout=5)
        assert not provider._sync_thread.is_alive()
    assert len(calls) == 2
