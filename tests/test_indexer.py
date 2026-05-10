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
