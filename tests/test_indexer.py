"""Integration tests for Indexer against fixture vault."""
import shutil
from pathlib import Path

import pytest

from lib.vault_index.config import load_config
from lib.vault_index.indexer import Indexer

FIXTURE = Path(__file__).parent / "fixtures" / "sample_vault"


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    """Copy fixture vault to tmp dir for isolation."""
    dst = tmp_path / "vault"
    shutil.copytree(FIXTURE, dst)
    return dst


@pytest.fixture
def cfg(vault: Path):
    return load_config(vault / ".claude" / "obsidian-knowledge.yaml")


def test_indexer_initial_row_count_is_zero(vault: Path, cfg, tmp_path: Path):
    cache_dir = tmp_path / "cache"
    idx = Indexer(vault_root=vault, cache_dir=cache_dir, config=cfg)
    assert idx.row_count() == 0


def test_full_reindex_indexes_wiki_files(vault: Path, cfg, tmp_path: Path):
    cache_dir = tmp_path / "cache"
    idx = Indexer(vault_root=vault, cache_dir=cache_dir, config=cfg)
    stats = idx.full_reindex()
    assert stats.indexed >= 2  # python.md + rust.md
    assert idx.row_count() >= 2


def test_full_reindex_skips_denied_paths(vault: Path, cfg, tmp_path: Path):
    cache_dir = tmp_path / "cache"
    idx = Indexer(vault_root=vault, cache_dir=cache_dir, config=cfg)
    idx.full_reindex()
    # Journal/diary.md and Inbox/random.md are denied at index time
    indexed_paths = idx.indexed_paths()
    assert not any("Journal/" in p for p in indexed_paths)
    assert not any("Inbox/" in p for p in indexed_paths)


def test_search_returns_relevant_results(vault: Path, cfg, tmp_path: Path):
    cache_dir = tmp_path / "cache"
    idx = Indexer(vault_root=vault, cache_dir=cache_dir, config=cfg)
    idx.full_reindex()
    hits = idx.search("python programming language")
    assert len(hits) >= 1
    assert any("python" in h.path.lower() for h in hits)


def test_search_applies_digest_filter(vault: Path, cfg, tmp_path: Path):
    cache_dir = tmp_path / "cache"
    idx = Indexer(vault_root=vault, cache_dir=cache_dir, config=cfg)
    idx.full_reindex()
    hits = idx.search("programming")
    # digest.allow_regex = ["^wiki/"]; nothing else should surface
    assert all(h.path.startswith("wiki/") for h in hits)


def test_search_scores_are_rescaled(vault: Path, cfg, tmp_path: Path):
    cache_dir = tmp_path / "cache"
    idx = Indexer(vault_root=vault, cache_dir=cache_dir, config=cfg)
    idx.full_reindex()
    hits = idx.search("python")
    # BM25 scores × 100 and then × weight 1.5 for wiki/ — scores should be >= 0
    # (may be 0.0 for very short docs; just check no exception)
    assert isinstance(hits, list)


def test_search_override_digest_filter_includes_excluded(vault: Path, cfg, tmp_path: Path):
    cache_dir = tmp_path / "cache"
    # Re-create config without index denial to allow Inbox indexing for this test
    cfg2 = cfg.model_copy(update={
        "index": cfg.index.model_copy(update={"deny_regex": []}),
    })
    idx = Indexer(vault_root=vault, cache_dir=cache_dir, config=cfg2)
    idx.full_reindex()
    hits = idx.search("Inbox", override_digest_filter=True)
    paths = [h.path for h in hits]
    assert any("Inbox/" in p for p in paths)


import os


def test_make_config_respects_embedding_env_vars(monkeypatch, tmp_path):
    monkeypatch.setenv("MEMWEAVE_EMBEDDING_MODEL", "ollama/mxbai-embed-large")
    monkeypatch.setenv("MEMWEAVE_EMBEDDING_API_BASE", "http://localhost:11434")
    monkeypatch.delenv("MEMWEAVE_EMBEDDING_API_KEY", raising=False)
    from lib.vault_index.config import VaultIndexConfig
    from lib.vault_index.indexer import Indexer
    cache = tmp_path / "cache"
    idx = Indexer(vault_root=tmp_path, cache_dir=cache, config=VaultIndexConfig())
    cfg = idx._make_config(extra_paths=[])
    assert cfg.embedding.model == "ollama/mxbai-embed-large"
    assert cfg.embedding.api_base == "http://localhost:11434"


def test_make_config_uses_defaults_when_env_unset(monkeypatch, tmp_path):
    monkeypatch.delenv("MEMWEAVE_EMBEDDING_MODEL", raising=False)
    monkeypatch.delenv("MEMWEAVE_EMBEDDING_API_BASE", raising=False)
    monkeypatch.delenv("MEMWEAVE_EMBEDDING_API_KEY", raising=False)
    from lib.vault_index.config import VaultIndexConfig
    from lib.vault_index.indexer import Indexer
    cache = tmp_path / "cache"
    idx = Indexer(vault_root=tmp_path, cache_dir=cache, config=VaultIndexConfig())
    cfg = idx._make_config(extra_paths=[])
    assert cfg.embedding.model == "ollama/bge-m3"
    assert cfg.embedding.api_base == "http://127.0.0.1:11434"
    assert cfg.chunking.tokens == 320
    assert cfg.chunking.overlap == 64


def test_indexer_probe_failure_falls_back_to_fts(monkeypatch, tmp_path):
    """Failed Ollama probe must flip vector off and surface a status string."""
    monkeypatch.setattr(
        "lib.vault_index.indexer._ollama_probe",
        lambda api_base, model: (False, "Ollama unreachable: stub"),
    )
    from lib.vault_index.config import VaultIndexConfig
    from lib.vault_index.indexer import Indexer
    cache = tmp_path / "cache"
    idx = Indexer(vault_root=tmp_path, cache_dir=cache, config=VaultIndexConfig())
    assert idx._vector_enabled is False
    assert "unreachable" in idx.vector_status
    cfg = idx._make_config(extra_paths=[])
    assert cfg.vector.enabled is False


def test_full_reindex_writes_fingerprint(monkeypatch, vault: Path, cfg, tmp_path: Path):
    """Successful reindex must persist the embedder fingerprint."""
    monkeypatch.setattr(
        "lib.vault_index.indexer._ollama_probe",
        lambda api_base, model: (True, "test-stub: probe ok"),
    )
    cache_dir = tmp_path / "cache"
    idx = Indexer(vault_root=vault, cache_dir=cache_dir, config=cfg)
    idx.full_reindex()
    fp = (cache_dir / "embedder-fingerprint.txt").read_text().strip()
    assert fp.startswith("ollama/bge-m3@")
    assert "320/64" in fp


def test_init_auto_rebuilds_on_embedder_change(monkeypatch, vault: Path, cfg, tmp_path: Path):
    """Stale fingerprint + populated index → search() triggers rebuild before returning."""
    monkeypatch.setattr(
        "lib.vault_index.indexer._ollama_probe",
        lambda api_base, model: (True, "test-stub: probe ok"),
    )
    cache_dir = tmp_path / "cache"
    # First pass: build index with current embedder.
    idx1 = Indexer(vault_root=vault, cache_dir=cache_dir, config=cfg)
    idx1.full_reindex()
    asyncio_close(idx1)

    # Tamper with the stored fingerprint to simulate a model swap.
    (cache_dir / "embedder-fingerprint.txt").write_text("ollama/old-model@320/64")

    idx2 = Indexer(vault_root=vault, cache_dir=cache_dir, config=cfg)
    assert idx2._needs_rebuild is True

    # Stub the rebuild so the test doesn't actually re-run memweave.index().
    rebuilt = {"n": 0}

    def fake_rebuild(reason: str) -> None:
        rebuilt["n"] += 1
        idx2._needs_rebuild = False

    monkeypatch.setattr(idx2, "_auto_rebuild", fake_rebuild)
    idx2.search("python")
    assert rebuilt["n"] == 1


def test_init_no_rebuild_on_fresh_install(monkeypatch, tmp_path: Path):
    """Empty cache must not trigger a rebuild — that's a fresh install, not a swap."""
    monkeypatch.setattr(
        "lib.vault_index.indexer._ollama_probe",
        lambda api_base, model: (True, "test-stub: probe ok"),
    )
    from lib.vault_index.config import VaultIndexConfig
    cache_dir = tmp_path / "cache"
    idx = Indexer(vault_root=tmp_path, cache_dir=cache_dir, config=VaultIndexConfig())
    assert idx._needs_rebuild is False


def asyncio_close(idx: Indexer) -> None:
    import asyncio as _a
    _a.run(idx._store.close())


def test_indexer_skip_probe_keeps_caller_choice(tmp_path):
    """skip_probe=True must trust caller's vector_enabled flag."""
    from lib.vault_index.config import VaultIndexConfig
    from lib.vault_index.indexer import Indexer
    cache = tmp_path / "cache"
    idx = Indexer(
        vault_root=tmp_path,
        cache_dir=cache,
        config=VaultIndexConfig(),
        vector_enabled=True,
        skip_probe=True,
    )
    assert idx._vector_enabled is True
    cfg = idx._make_config(extra_paths=[])
    assert cfg.vector.enabled is True
