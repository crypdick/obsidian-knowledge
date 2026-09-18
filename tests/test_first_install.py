"""First-run indexing and later semantic-search activation."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from lib.vault_index.cli import setup
from lib.vault_index.config import VaultIndexConfig
from lib.vault_index.indexer import Indexer


@pytest.fixture
def vault(tmp_path):
    root = tmp_path / "vault"
    root.mkdir()
    (root / "example.md").write_text("# Python\nPython is a programming language.\n")
    return root


@pytest.fixture
def embed(monkeypatch):
    async def vectors(texts):
        return [[1.0, 0.0] for _ in texts]

    provider = AsyncMock(side_effect=vectors)
    monkeypatch.setattr("memweave.embedding.provider.LiteLLMEmbeddingProvider._embed_one_batch", provider)
    return provider


@pytest.mark.parametrize("vector_enabled", [True, False])
def test_keyword_index_never_requests_embeddings(vault, tmp_path, embed, vector_enabled):
    idx = Indexer(vault, tmp_path / "cache", VaultIndexConfig(), vector_enabled=vector_enabled)
    try:
        assert idx.full_reindex().indexed == 1
        assert idx.sync().skipped == 1
        assert idx.full_reindex(force=True).indexed == 1
        assert idx.search("Python")[0].path == "example.md"
        embed.assert_not_awaited()
    finally:
        asyncio.run(idx._store.close())


def test_enabling_ollama_embeds_unchanged_keyword_index(vault, tmp_path, monkeypatch, embed):
    cache = tmp_path / "cache"
    idx = Indexer(vault, cache, VaultIndexConfig())
    idx.full_reindex()
    asyncio.run(idx._store.close())
    embed.assert_not_awaited()

    monkeypatch.setattr("lib.vault_index.indexer._ollama_probe", lambda *_: (True, "available"))
    idx = Indexer(vault, cache, VaultIndexConfig())
    try:
        # No file changes or --force: enabling semantic search must embed old files.
        assert idx.full_reindex().indexed == 1
        embed.assert_awaited()
    finally:
        asyncio.run(idx._store.close())

    embed.reset_mock()
    idx = Indexer(vault, cache, VaultIndexConfig())
    try:
        assert idx.full_reindex().skipped == 1
        embed.assert_not_awaited()
    finally:
        asyncio.run(idx._store.close())


def test_offline_updates_are_embedded_when_ollama_returns(vault, tmp_path, monkeypatch, embed):
    cache = tmp_path / "cache"
    monkeypatch.setattr("lib.vault_index.indexer._ollama_probe", lambda *_: (True, "available"))
    idx = Indexer(vault, cache, VaultIndexConfig())
    idx.full_reindex()
    asyncio.run(idx._store.close())

    (vault / "example.md").write_text("# Rust\nRust is a systems programming language.\n")
    idx = Indexer(vault, cache, VaultIndexConfig(), vector_enabled=False)
    idx.sync()
    asyncio.run(idx._store.close())

    embed.reset_mock()
    idx = Indexer(vault, cache, VaultIndexConfig())
    try:
        assert idx.sync().indexed == 1
        assert any("Rust" in text for call in embed.call_args_list for text in call.args[0])
    finally:
        asyncio.run(idx._store.close())


@pytest.mark.parametrize("install_guards", [False, True])
def test_setup_without_ollama_finishes_and_explains_search_mode(
    vault, tmp_path, monkeypatch, capsys, embed, install_guards
):
    registry = tmp_path / "config" / "vaults.yaml"
    monkeypatch.setenv("OBSIDIAN_KNOWLEDGE_VAULTS_CONFIG", str(registry))
    monkeypatch.setattr("shutil.which", lambda _: None)
    installed = []

    def record_install(base):
        installed.append(base)
        return base / ".i-insist/obsidian-knowledge.toml"

    monkeypatch.setattr("lib.vault_index.guard_install.install_rules", record_install)
    if install_guards:
        setup(vault, install_guards=True)
    else:
        setup(vault)
    assert installed == ([Path.home()] if install_guards else [])
    output = capsys.readouterr().out
    assert "Search mode: keyword-only" in output
    assert "Setup complete." in output
    assert str(vault) in registry.read_text()
    embed.assert_not_awaited()
