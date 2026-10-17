"""Read-only index inspection and bounded update output contracts."""

import sqlite3
from contextlib import closing

import pytest

from lib.vault_index.cli import default_cache_dir_for_vault
from lib.vault_index.mcp_index import parse_index_update, read_index_status


def make_index(vault, *, vector=False, fingerprint=None, count=2):
    cache = default_cache_dir_for_vault(vault)
    cache.mkdir(parents=True)
    with closing(sqlite3.connect(cache / "index.sqlite")) as connection:
        connection.execute("CREATE TABLE files (path TEXT)")
        connection.executemany("INSERT INTO files VALUES (?)", [(f"note-{i}.md",) for i in range(count)])
        if vector:
            connection.execute("CREATE TABLE chunks_vec (id INTEGER)")
        connection.commit()
    if fingerprint is not None:
        (cache / "embedder-fingerprint.txt").write_text(fingerprint)
    return cache


def test_absent_index_status_does_not_create_cache(tmp_path):
    cache = default_cache_dir_for_vault(tmp_path)
    result = read_index_status(tmp_path)
    assert result.model_dump() == {
        "index_exists": False,
        "indexed_files": None,
        "vector_index_ready": False,
        "degraded_reason": "index absent",
    }
    assert not cache.exists()


@pytest.mark.parametrize(
    ("vector", "fingerprint", "count", "reason"),
    [
        (False, "keyword-only", 2, "index built in keyword-only mode"),
        (True, "ollama/old@320/64", 2, "embedding settings changed; update required"),
        (False, "ollama/bge-m3@320/64", 2, "vector index unavailable"),
        (True, None, 2, "embedding fingerprint unavailable"),
        (True, "ollama/bge-m3@320/64", 0, "index empty"),
        (True, "ollama/bge-m3@320/64", 2, None),
    ],
)
def test_index_metadata_reports_persisted_readiness(
    tmp_path, monkeypatch, vector, fingerprint, count, reason
):
    monkeypatch.delenv("MEMWEAVE_EMBEDDING_MODEL", raising=False)
    cache = make_index(tmp_path, vector=vector, fingerprint=fingerprint, count=count)
    before = {path.name: path.read_bytes() for path in cache.iterdir()}
    result = read_index_status(tmp_path)
    assert result.index_exists
    assert result.indexed_files == count
    assert result.vector_index_ready is (reason is None)
    assert result.degraded_reason == reason
    assert {path.name: path.read_bytes() for path in cache.iterdir()} == before


def test_index_status_uses_current_embedding_model(tmp_path, monkeypatch):
    monkeypatch.setenv("MEMWEAVE_EMBEDDING_MODEL", "ollama/custom")
    make_index(tmp_path, vector=True, fingerprint="ollama/custom@320/64")
    assert read_index_status(tmp_path).vector_index_ready


def test_pending_rebuild_is_not_ready_despite_matching_fingerprint(tmp_path):
    cache = make_index(tmp_path, vector=True, fingerprint="ollama/bge-m3@320/64")
    with closing(sqlite3.connect(cache / "index.sqlite")) as connection:
        connection.execute("CREATE TABLE meta (key TEXT PRIMARY KEY,value TEXT)")
        connection.execute("INSERT INTO meta VALUES ('memory_index_rebuild_v1','{}')")
        connection.commit()
    status = read_index_status(tmp_path)
    assert not status.vector_index_ready
    assert status.degraded_reason == "vector index rebuild incomplete; update required"


def test_corrupt_index_reports_unknown_count_without_repair(tmp_path):
    cache = default_cache_dir_for_vault(tmp_path)
    cache.mkdir(parents=True)
    database = cache / "index.sqlite"
    database.write_bytes(b"not sqlite")
    result = read_index_status(tmp_path)
    assert result.index_exists
    assert result.indexed_files is None
    assert not result.vector_index_ready
    assert result.degraded_reason.startswith("index unreadable: ")
    assert database.read_bytes() == b"not sqlite"


@pytest.mark.parametrize("invalid_utf8", [False, True])
def test_unreadable_fingerprint_reports_unknown_readiness(tmp_path, invalid_utf8):
    cache = make_index(tmp_path, vector=True)
    marker = cache / "embedder-fingerprint.txt"
    if invalid_utf8:
        marker.write_bytes(b"\xff")
    else:
        marker.mkdir()
    assert read_index_status(tmp_path).degraded_reason == "embedding fingerprint unavailable"


def test_update_output_reports_counts():
    result = parse_index_update(b"Indexed: 2, Skipped: 3, Deleted: 4\n", b"")
    assert result.model_dump() == {"status": "updated", "indexed": 2, "skipped": 3, "deleted": 4}


def test_update_busy_does_not_claim_success():
    result = parse_index_update(
        b"", b"reindex: another index operation is in progress (lock held); exiting cleanly.\n"
    )
    assert result.model_dump() == {"status": "busy", "indexed": None, "skipped": None, "deleted": None}


@pytest.mark.parametrize(
    "stdout", [b"", b"Indexed: -1, Skipped: 3, Deleted: 4", b"Indexed: 1, Skipped: 2, Deleted: 3 junk"]
)
def test_update_rejects_unrecognized_output(stdout):
    with pytest.raises(ValueError, match="unexpected reindex output"):
        parse_index_update(stdout, b"")


def test_index_status_accepts_relative_cache_root(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OBSIDIAN_KNOWLEDGE_CACHE_ROOT", "relative-cache")
    make_index(tmp_path)
    assert read_index_status(tmp_path).indexed_files == 2
