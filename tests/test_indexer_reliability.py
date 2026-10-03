"""Failure recovery and output-quality tests for vault retrieval."""

from __future__ import annotations

import asyncio
import errno
import fcntl
import io
import json
import sqlite3
import subprocess
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from pathlib import Path
from threading import Event
from types import SimpleNamespace

import memweave
import pytest

from lib.vault_index import indexer
from lib.vault_index.config import VaultIndexConfig
from lib.vault_index.embeddings import KeywordOnlyEmbeddingProvider
from lib.vault_index.models import Hit, IndexBusyError

REAL_OLLAMA_PROBE = indexer._ollama_probe


def close(instance: indexer.Indexer) -> None:
    asyncio.run(instance._store.close())


@pytest.mark.parametrize(
    ("api_base", "payload", "expected"),
    [
        ("unix:///ollama.sock", None, "api_base not http"),
        ("http://ollama", b"not json", "returned non-JSON"),
        ("http://ollama", b'{"models": [{"name": "bge-m3:latest"}]}', "ok: bge-m3"),
    ],
)
def test_ollama_probe_validates_endpoint_and_response(monkeypatch, api_base, payload, expected):
    if payload is not None:
        monkeypatch.setattr(urllib.request, "urlopen", lambda *args, **kwargs: io.BytesIO(payload))
    ok, message = REAL_OLLAMA_PROBE(api_base, "ollama/bge-m3")
    assert ok is expected.startswith("ok:")
    assert expected in message


def test_keyword_only_provider_returns_empty_vectors():
    provider = KeywordOnlyEmbeddingProvider()
    assert asyncio.run(provider.embed_query("query")) == []
    assert asyncio.run(provider.embed_batch(["one", "two"])) == [[], []]


def test_keyword_index_and_search_do_not_import_litellm(tmp_path):
    script = """
import json, sys, asyncio
from pathlib import Path
from lib.vault_index.indexer import Indexer
from lib.vault_index.config import VaultIndexConfig
root = Path(sys.argv[1])
(root / 'note.md').write_text('Purple orchids grow in a greenhouse.')
instance = Indexer(root, root / 'cache', VaultIndexConfig(), vector_enabled=False)
instance.full_reindex()
hits = instance.search('orchids')
asyncio.run(instance._store.close())
print(json.dumps({'paths': [hit.path for hit in hits], 'litellm_loaded': 'litellm' in sys.modules}))
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path)], capture_output=True, text=True, timeout=20
    )
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["paths"] == ["note.md"]
    assert report["litellm_loaded"] is False


def test_indexer_falls_back_when_preferred_cache_is_unwritable(tmp_path, monkeypatch):
    preferred = tmp_path / "preferred"
    sandbox = tmp_path / "sandbox"
    real_mkdir = Path.mkdir

    def mkdir(path, *args, **kwargs):
        if path == preferred:
            raise OSError(errno.EROFS, "read-only")
        return real_mkdir(path, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", mkdir)
    monkeypatch.setattr(indexer, "SANDBOX_CACHE_ROOT", sandbox)
    instance = indexer.Indexer(
        tmp_path,
        preferred,
        VaultIndexConfig(),
        vector_enabled=False,
    )
    try:
        assert instance.cache_dir == sandbox / indexer.APP_NAME / preferred.name
        assert instance.cache_dir.is_dir()
    finally:
        close(instance)


@pytest.mark.parametrize("with_vector_table", [False, True])
def test_pre_fingerprint_cache_rebuild_depends_on_vector_table(tmp_path, with_vector_table):
    cache = tmp_path / "cache"
    cache.mkdir()
    db = cache / "index.sqlite"
    with sqlite3.connect(db) as connection:
        if with_vector_table:
            connection.execute("CREATE TABLE chunks_vec (id INTEGER)")
    instance = indexer.Indexer(
        tmp_path,
        cache,
        VaultIndexConfig(),
        vector_enabled=True,
        skip_probe=True,
    )
    try:
        assert instance._needs_rebuild is (not with_vector_table)
    finally:
        close(instance)


def test_corrupt_vector_database_is_treated_as_missing_table(tmp_path):
    db = tmp_path / "index.sqlite"
    db.write_text("not sqlite")
    assert indexer.Indexer._vector_table_exists(db) is False


def test_embedding_api_key_is_forwarded_to_memweave(tmp_path, monkeypatch):
    monkeypatch.setenv("MEMWEAVE_EMBEDDING_API_KEY", "synthetic-key")  # pragma: allowlist secret
    instance = indexer.Indexer(tmp_path, tmp_path / "cache", VaultIndexConfig(), vector_enabled=False)
    try:
        assert instance._make_config([]).embedding.api_key == "synthetic-key"  # pragma: allowlist secret
    finally:
        close(instance)


def test_paths_outside_vault_remain_absolute(tmp_path):
    instance = indexer.Indexer(tmp_path, tmp_path / "cache", VaultIndexConfig(), vector_enabled=False)
    try:
        assert instance._abs_to_rel("/outside/note.md") == "/outside/note.md"
    finally:
        close(instance)


def test_search_snippets_handle_long_missing_empty_and_traversal_files(tmp_path, monkeypatch):
    (tmp_path / "long.md").write_text("prefix " * 60 + "needle " + "suffix " * 60)
    (tmp_path / "empty.md").write_text("\n\n")
    instance = indexer.Indexer(tmp_path, tmp_path / "cache", VaultIndexConfig(top_k=10), vector_enabled=False)
    hits = [
        Hit(path="long.md", score=10, weight_applied=1),
        Hit(path="empty.md", score=9, weight_applied=1),
        Hit(path="missing.md", score=8, weight_applied=1),
        Hit(path="../outside.md", score=7, weight_applied=1),
    ]
    monkeypatch.setattr(instance, "_sqlite_fts_search", lambda query, count: hits)
    try:
        result = instance.search("needle", top_k=10, min_score=0.0)
    finally:
        close(instance)
    snippets = {hit.path: hit.snippet for hit in result}
    assert "needle" in snippets["long.md"]
    assert len(snippets["long.md"]) <= indexer.SNIPPET_MAX_CHARS + 6
    assert snippets["long.md"].startswith("...") and snippets["long.md"].endswith("...")
    assert snippets["empty.md"] == ""
    assert snippets["missing.md"] == ""
    assert snippets["../outside.md"] == ""


def test_snippet_falls_back_to_first_line_when_query_has_no_match(tmp_path, monkeypatch):
    (tmp_path / "note.md").write_text("short first line\na much longer second line")
    instance = indexer.Indexer(tmp_path, tmp_path / "cache", VaultIndexConfig(), vector_enabled=False)
    monkeypatch.setattr(
        instance,
        "_sqlite_fts_search",
        lambda query, count: [Hit(path="note.md", score=1, weight_applied=1)],
    )
    try:
        assert instance.search("absent")[0].snippet == "short first line"
        assert instance.search("!!!")[0].snippet == "short first line"
    finally:
        close(instance)


def test_fts_search_is_empty_without_database_and_on_invalid_database(tmp_path):
    instance = indexer.Indexer(tmp_path, tmp_path / "cache", VaultIndexConfig(), vector_enabled=False)
    try:
        assert instance._sqlite_fts_search("query", 5) == []
        (instance.cache_dir / "index.sqlite").write_text("not sqlite")
        assert instance._sqlite_fts_search("query", 5) == []
    finally:
        close(instance)


def test_snippet_crop_handles_match_near_end_and_one_sided_ellipsis():
    text = "prefix " * 70 + "needle"
    snippet = indexer.Indexer._crop_snippet(text, ["needle"])
    assert snippet.startswith("...")
    assert snippet.endswith("needle")

    beginning = indexer.Indexer._crop_snippet("needle " + "suffix " * 80, ["needle"])
    assert beginning.startswith("needle")
    assert beginning.endswith("...")


def test_invalid_fts_query_with_no_safe_terms_returns_empty(tmp_path, monkeypatch):
    instance = indexer.Indexer(tmp_path, tmp_path / "cache", VaultIndexConfig(), vector_enabled=False)
    (instance.cache_dir / "index.sqlite").touch()
    monkeypatch.setattr(
        sqlite3,
        "connect",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(sqlite3.DatabaseError("bad query")),
    )
    try:
        assert instance._sqlite_fts_search("!!!", 5) == []
    finally:
        close(instance)


@pytest.mark.parametrize("retry_safe_query", [False, True])
def test_keyword_search_reports_database_contention(tmp_path, monkeypatch, retry_safe_query):
    instance = indexer.Indexer(tmp_path, tmp_path / "cache", VaultIndexConfig(), vector_enabled=False)
    (instance.cache_dir / "index.sqlite").touch()
    failures = [sqlite3.OperationalError("database is locked")]
    if retry_safe_query:
        failures.insert(0, sqlite3.DatabaseError("invalid FTS query"))

    def connect(*args, **kwargs):
        raise failures.pop(0)

    monkeypatch.setattr(sqlite3, "connect", connect)
    try:
        with pytest.raises(IndexBusyError, match="database is locked"):
            instance.search("query")
    finally:
        close(instance)


def test_blocking_index_lock_does_not_request_nonblocking_mode(tmp_path, monkeypatch):
    modes = []
    monkeypatch.setattr(fcntl, "flock", lambda _file, mode: modes.append(mode))
    with indexer.index_lock(tmp_path, exclusive=False, blocking=True):
        pass
    assert modes[0] == fcntl.LOCK_SH


def vector_indexer(tmp_path) -> indexer.Indexer:
    return indexer.Indexer(
        tmp_path,
        tmp_path / "cache",
        VaultIndexConfig(),
        vector_enabled=True,
        skip_probe=True,
    )


def test_vector_search_waits_for_writer_then_returns_results(tmp_path):
    instance = vector_indexer(tmp_path)
    lock = open(instance.cache_dir / ".index.sqlite.lock", "w")
    started = Event()

    async def search(*args, **kwargs):
        return [SimpleNamespace(path=str(tmp_path / "note.md"), score=0.5)]

    instance._store.search = search

    def retrieve():
        started.set()
        return instance.search("query")

    try:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        with ThreadPoolExecutor(max_workers=1) as executor:
            try:
                pending = executor.submit(retrieve)
                assert started.wait(5)
                with pytest.raises(FutureTimeoutError):
                    pending.result(timeout=0.1)
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
            assert pending.result(timeout=5) == [Hit(path="note.md", score=50.0, weight_applied=1.0)]
    finally:
        fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
        lock.close()
        close(instance)


@pytest.mark.parametrize(
    ("error", "expected_error"),
    [
        (sqlite3.OperationalError("database is locked"), IndexBusyError),
        (memweave.StorageError("database is locked"), IndexBusyError),
        (sqlite3.OperationalError("disk failure"), sqlite3.OperationalError),
    ],
)
@pytest.mark.parametrize("rebuild_before_error", [False, True])
def test_vector_search_handles_only_lock_storage_errors(
    tmp_path, monkeypatch, error, expected_error, rebuild_before_error
):
    instance = vector_indexer(tmp_path)
    calls = 0

    async def fail(*args, **kwargs):
        nonlocal calls
        calls += 1
        if rebuild_before_error and calls == 1:
            raise memweave.SearchError("no such table: chunks_vec")
        raise error

    instance._store.search = fail
    monkeypatch.setattr(instance, "_auto_rebuild", lambda reason: None)
    try:
        with pytest.raises(expected_error, match=str(error)):
            instance.search("query")
    finally:
        close(instance)


def test_missing_vector_table_can_fall_back_without_rebuild(tmp_path, monkeypatch):
    instance = vector_indexer(tmp_path)

    async def fail(*args, **kwargs):
        raise memweave.SearchError("no such table: chunks_vec")

    instance._store.search = fail
    fallback = [Hit(path="note.md", score=1, weight_applied=1)]
    monkeypatch.setattr(instance, "_sqlite_fts_search", lambda query, count: fallback)
    monkeypatch.setattr(instance, "_with_snippets", lambda hits, query: hits)
    try:
        assert instance.search("query", allow_rebuild=False) == fallback
    finally:
        close(instance)


def test_missing_vector_table_rebuilds_and_retries_once(tmp_path, monkeypatch):
    instance = vector_indexer(tmp_path)
    calls = 0

    async def search(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise memweave.SearchError("no such table: chunks_vec")
        return [SimpleNamespace(path=str(tmp_path / "note.md"), score=0.5)]

    instance._store.search = search
    monkeypatch.setattr(instance, "_auto_rebuild", lambda reason: None)
    monkeypatch.setattr(instance, "_with_snippets", lambda hits, query: hits)
    try:
        result = instance.search("query")
        assert result == [Hit(path="note.md", score=50.0, weight_applied=1.0)]
        assert calls == 2
    finally:
        close(instance)


def test_missing_vector_table_does_not_hide_rebuild_contention(tmp_path, monkeypatch):
    instance = vector_indexer(tmp_path)

    async def fail(*args, **kwargs):
        raise memweave.SearchError("no such table: chunks_vec")

    instance._store.search = fail
    monkeypatch.setattr(
        instance,
        "_auto_rebuild",
        lambda reason: (_ for _ in ()).throw(IndexBusyError("busy")),
    )
    try:
        with pytest.raises(IndexBusyError, match="busy"):
            instance.search("query")
    finally:
        close(instance)


def test_query_embedding_failure_falls_back_to_keyword_search(tmp_path, monkeypatch):
    instance = vector_indexer(tmp_path)

    async def fail(*args, **kwargs):
        raise memweave.SearchError("VectorSearch requires a query_vec (got None)")

    instance._store.search = fail
    fallback = [Hit(path="note.md", score=1, weight_applied=1)]
    monkeypatch.setattr(instance, "_sqlite_fts_search", lambda query, count: fallback)
    monkeypatch.setattr(instance, "_with_snippets", lambda hits, query: hits)
    try:
        assert instance.search("/data/Videos/Movies") == fallback
    finally:
        close(instance)


def test_unrelated_memweave_search_error_is_not_hidden(tmp_path):
    instance = vector_indexer(tmp_path)

    async def fail(*args, **kwargs):
        raise memweave.SearchError("unrelated failure")

    instance._store.search = fail
    try:
        with pytest.raises(memweave.SearchError, match="unrelated failure"):
            instance.search("query")
    finally:
        close(instance)


def test_auto_rebuild_reports_reason_and_forces_reindex(tmp_path, monkeypatch, capsys):
    instance = vector_indexer(tmp_path)
    calls = []
    monkeypatch.setattr(
        instance, "full_reindex", lambda force=False, *, blocking=False: calls.append((force, blocking))
    )
    try:
        instance._auto_rebuild("model changed")
    finally:
        close(instance)
    assert calls == [(True, True)]
    assert "rebuilding (model changed" in capsys.readouterr().err
