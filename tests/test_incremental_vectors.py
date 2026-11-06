"""Vector indexing makes forward progress without rebuilding valid vectors."""

from __future__ import annotations

import asyncio
import fcntl
import json
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from lib.vault_index.config import VaultIndexConfig
from lib.vault_index.indexer import Indexer, default_cache_dir
from lib.vault_index.mcp_server import create_server
from obsidian_knowledge_vendor.memweave.embedding import checkpoint

CONFIG = VaultIndexConfig()


def make_vault(root: Path, count: int = 3) -> Path:
    vault = root / "vault"
    (vault / "wiki").mkdir(parents=True)
    for number in range(count):
        (vault / f"wiki/note{number}.md").write_text(
            f"# Note {number}\n\nOrchid greenhouse topic {number}.\n"
        )
    return vault


def close(instance: Indexer) -> None:
    asyncio.run(instance._store.close())


def run_cli(*arguments: str | Path, stdin: str | None = None, timeout: float = 30):
    return subprocess.run(
        [sys.executable, "-m", "lib.vault_index.cli", *map(str, arguments)],
        input=stdin,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def build_index(vault: Path, cache: Path) -> None:
    instance = Indexer(vault, cache, CONFIG)
    instance.full_reindex()
    close(instance)


@pytest.fixture
def cache_root(tmp_path, monkeypatch):
    monkeypatch.setenv("OBSIDIAN_KNOWLEDGE_CACHE_ROOT", str(tmp_path / "cache-root"))


@pytest.mark.parametrize("pending", [False, True])
def test_first_search_embeds_nothing_and_reports_first_init(tmp_path, fake_ollama, pending):
    vault = make_vault(tmp_path)
    cache = tmp_path / "cache"
    if pending:
        # The state observed on a CPU-only host: an interrupted first build.
        cache.mkdir()
        with sqlite3.connect(cache / "index.sqlite") as connection:
            connection.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
            connection.execute("CREATE TABLE files (path TEXT PRIMARY KEY)")
            connection.execute("INSERT INTO meta VALUES ('memory_index_rebuild_v1', '{}')")
    instance = Indexer(vault, cache, CONFIG)
    try:
        assert instance.vector_issue == "index not built yet"
        report = instance.search_report("orchid")
    finally:
        close(instance)
    assert report.mode == "keyword"
    assert report.degraded_reason == "vector index requires reindex"
    assert fake_ollama.texts == []


def test_cli_search_leaves_indexing_to_worker(tmp_path, fake_ollama, cache_root, drain_index):
    vault = make_vault(tmp_path)
    result = run_cli("search", "orchid", "--json", "--vault", vault)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["degraded_reason"] == "vector index requires reindex"
    assert fake_ollama.texts == []
    assert not (default_cache_dir(vault) / "background-reindex.log").exists()
    asyncio.run(drain_index(vault))
    result = run_cli("search", "orchid", "--json", "--vault", vault)
    assert json.loads(result.stdout)["mode"] == "hybrid"


def test_cli_search_does_not_start_second_reindex_while_writer_runs(tmp_path, fake_ollama, cache_root):
    vault = make_vault(tmp_path)
    cache = default_cache_dir(vault)
    cache.mkdir(parents=True)
    with (cache / ".index.sqlite.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        result = run_cli("search", "orchid", "--json", "--vault", vault)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["degraded_reason"] == "vector index requires reindex"
    assert "already running" not in result.stderr
    assert not (cache / "background-reindex.log").exists()


def test_interrupted_slow_reindex_keeps_completed_embeddings(tmp_path, monkeypatch, fake_ollama):
    vault = tmp_path / "vault"
    (vault / "wiki").mkdir(parents=True)

    def paragraphs(note: int, count: int) -> str:
        return "\n\n".join(
            f"Paragraph {note}-{part} " + "orchid greenhouse " * 60 + f"marker{note}x{part}"
            for part in range(count)
        )

    # One file large enough to bypass cross-file prefetch, plus small files.
    (vault / "wiki/big.md").write_text(paragraphs(0, 30))
    for note in range(1, 7):
        (vault / f"wiki/small{note}.md").write_text(paragraphs(note, 2))

    # A CPU-only embedder: 2.3 s of (simulated) wall time per chunk.
    clock = SimpleNamespace(now=0.0)
    monkeypatch.setattr(checkpoint, "time", SimpleNamespace(monotonic=lambda: clock.now))

    class Interrupted(BaseException):
        """Stands in for a kill or deadline in the middle of an embed request."""

    completed: list[str] = []
    attempted: list[int] = []

    async def slow_embed(self, texts):
        attempted.append(len(texts))
        if len(completed) + len(texts) > 12:
            raise Interrupted
        clock.now += 2.3 * len(texts)
        completed.extend(texts)
        return [[1.0, float(len(text) % 7)] for text in texts]

    monkeypatch.setattr("lib.vault_index.embeddings.OllamaEmbeddingProvider.embed_batch", slow_embed)
    cache = tmp_path / "cache"
    first = Indexer(vault, cache, CONFIG)
    with pytest.raises(Interrupted):
        first.full_reindex()

    def counting(into: list[str]):
        async def embed(self, texts):
            into.extend(texts)
            return [[1.0, float(len(text) % 7)] for text in texts]

        return embed

    remainder: list[str] = []
    monkeypatch.setattr("lib.vault_index.embeddings.OllamaEmbeddingProvider.embed_batch", counting(remainder))
    second = Indexer(vault, cache, CONFIG)
    second.full_reindex()
    close(second)
    everything: list[str] = []
    monkeypatch.setattr(
        "lib.vault_index.embeddings.OllamaEmbeddingProvider.embed_batch", counting(everything)
    )
    reference = Indexer(vault, tmp_path / "reference-cache", CONFIG)
    reference.full_reindex()
    close(reference)

    assert completed, "the slow run must have finished some batches"
    assert max(attempted) <= 4, "slow embedders must checkpoint in small batches"
    assert attempted[-1] <= 3, "an interruption may lose only a few chunks"
    assert set(completed).isdisjoint(remainder)
    assert sorted(completed + remainder) == sorted(everything)


def test_offline_sync_backfills_only_missing_vectors(tmp_path, monkeypatch, fake_ollama):
    vault = make_vault(tmp_path)
    cache = tmp_path / "cache"
    build_index(vault, cache)

    (vault / "wiki/note0.md").write_text("# Note 0\n\nEdited offline about cacti.\n")
    offline = Indexer(vault, cache, CONFIG, vector_enabled=False)
    offline.full_reindex()
    close(offline)

    fake_ollama.texts.clear()
    restored = Indexer(vault, cache, CONFIG)
    try:
        assert restored.vector_issue == "vectors missing after keyword-only sync"
        stale = restored.search_report("cacti")
        assert (stale.mode, stale.degraded_reason) == ("keyword", "vector index requires reindex")
        assert fake_ollama.texts == []
        stats = restored.full_reindex()
        assert (stats.indexed, stats.skipped) == (1, 2)
        assert len(fake_ollama.texts) == 1
        assert "cacti" in fake_ollama.texts[0]
        assert restored.vector_issue is None
        fresh = restored.search_report("cacti")
        assert fresh.mode == "hybrid"
        assert fresh.hits[0].path == "wiki/note0.md"
    finally:
        close(restored)

    fake_ollama.models = ("bge-m3:latest", "other-embed:latest")
    monkeypatch.setenv("MEMWEAVE_EMBEDDING_MODEL", "ollama/other-embed")
    changed = Indexer(vault, cache, CONFIG)
    try:
        assert changed.vector_issue == (
            "embedder changed (was ollama/bge-m3@320/64, now ollama/other-embed@320/64)"
        )
        assert changed.full_reindex().indexed == 3
    finally:
        close(changed)


def test_write_indexes_only_the_written_note(tmp_path, fake_ollama, cache_root, drain_index):
    vault = make_vault(tmp_path)
    cache = default_cache_dir(vault)
    build_index(vault, cache)
    fake_ollama.texts.clear()

    note = "# Fresh\n\nPelargonium cuttings root in perlite.\n"
    result = run_cli("write", "wiki/fresh.md", "--vault", vault, stdin=note)
    assert result.returncode == 0, result.stderr
    assert "Wrote and verified" in result.stdout
    assert fake_ollama.texts == []
    asyncio.run(drain_index(vault))
    assert len(fake_ollama.texts) == 1
    assert "Pelargonium" in fake_ollama.texts[0]

    fake_ollama.texts.clear()
    result = run_cli("write", "wiki/fresh.md", "--replace", "--vault", vault, stdin=note)
    assert result.returncode == 0, result.stderr
    assert fake_ollama.texts == []

    instance = Indexer(vault, cache, CONFIG)
    try:
        report = instance.search_report("Pelargonium")
    finally:
        close(instance)
    assert report.mode == "hybrid"
    assert report.hits[0].path == "wiki/fresh.md"


@pytest.mark.parametrize("failure", ["lock", "embedder-down", "embedder-slow"])
def test_write_succeeds_and_defers_indexing_when_index_unavailable(
    tmp_path, fake_ollama, cache_root, monkeypatch, failure
):
    vault = make_vault(tmp_path)
    cache = default_cache_dir(vault)
    build_index(vault, cache)
    lock = (cache / ".index.sqlite.lock").open("w")
    if failure == "lock":
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    elif failure == "embedder-down":
        monkeypatch.setenv("MEMWEAVE_EMBEDDING_API_BASE", "http://127.0.0.1:9")
    else:
        fake_ollama.delay = 20
        monkeypatch.setenv("OBSIDIAN_KNOWLEDGE_SEARCH_TTL_SECONDS", "2")
    started = time.monotonic()
    try:
        result = run_cli("write", "wiki/fresh.md", "--vault", vault, stdin="# Fresh\n\nCuttings.\n")
    finally:
        lock.close()
    assert result.returncode == 0, result.stderr
    assert "Wrote and verified" in result.stdout
    assert "next sync" not in result.stderr
    assert time.monotonic() - started < 15
    assert (vault / "wiki/fresh.md").read_text() == "# Fresh\n\nCuttings.\n"


def test_mcp_write_indexes_written_note(tmp_path, fake_ollama, cache_root, drain_index):
    vault = make_vault(tmp_path)
    build_index(vault, default_cache_dir(vault))
    fake_ollama.texts.clear()

    async def exercise():
        server = create_server(vault)
        result = await server.call_tool(
            "vault_write", {"path": "wiki/fresh.md", "content": "# Fresh\n\nAloe.\n"}
        )
        return result[1]

    assert asyncio.run(exercise())["index"] == "queued"
    assert fake_ollama.texts == []
    asyncio.run(drain_index(vault))
    assert len(fake_ollama.texts) == 1
    assert "Aloe" in fake_ollama.texts[0]


def test_upgrade_resumes_rebuild_started_by_previous_release(tmp_path, fake_ollama):
    vault = make_vault(tmp_path)
    cache = tmp_path / "cache"
    build_index(vault, cache)
    with sqlite3.connect(cache / "index.sqlite") as connection:
        (meta,) = connection.execute("SELECT value FROM meta WHERE key = 'memory_index_meta_v1'").fetchone()
        # Earlier releases recorded vector mode in the rebuild target.
        target = json.dumps({**json.loads(meta), "vector_enabled": True}, sort_keys=True)
        connection.execute("INSERT INTO meta VALUES ('memory_index_rebuild_v1', ?)", (target,))
        connection.execute("INSERT INTO index_rebuild_files SELECT path FROM files")
    instance = Indexer(vault, cache, CONFIG)
    try:
        assert instance.vector_issue == "index rebuild incomplete"
        assert instance.full_reindex().indexed == 0
        assert instance.vector_issue is None
    finally:
        close(instance)


def test_reindex_path_defers_until_vectors_ready_and_ignores_unknown_files(tmp_path, fake_ollama, cache_root):
    vault = make_vault(tmp_path)
    cache = default_cache_dir(vault)
    offline = Indexer(vault, cache, CONFIG, vector_enabled=False)
    offline.full_reindex()
    close(offline)

    result = run_cli("reindex", "--path", "wiki/note0.md", "--vault", vault)
    assert result.returncode == 3
    assert "vector index not ready (vectors missing after keyword-only sync)" in result.stderr

    build_index(vault, cache)
    result = run_cli("reindex", "--path", "wiki/missing.md", "--vault", vault)
    assert result.returncode == 0, result.stderr
    assert result.stdout == "Indexed: 0, Skipped: 0, Deleted: 0\n"


def test_index_without_vector_table_is_not_ready(tmp_path, fake_ollama):
    cache = tmp_path / "cache"
    cache.mkdir()
    with sqlite3.connect(cache / "index.sqlite") as connection:
        connection.execute("CREATE TABLE files (path TEXT PRIMARY KEY)")
        connection.execute("INSERT INTO files VALUES ('note.md')")
    (cache / "embedder-fingerprint.txt").write_text("ollama/bge-m3@320/64")
    instance = Indexer(tmp_path, cache, CONFIG)
    try:
        assert instance.vector_issue == "vector index unavailable"
    finally:
        close(instance)


def test_write_survives_a_wedged_index_process(tmp_path, monkeypatch, capsys):
    from lib.vault_index import cli

    def wedged(command, **kwargs):
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])

    monkeypatch.setattr(cli.subprocess, "run", wedged)
    cli.index_written_file(tmp_path, "wiki/note.md")
    assert capsys.readouterr().err == ""


def test_model_change_during_offline_sync_still_rebuilds_vectors(tmp_path, monkeypatch, fake_ollama):
    vault = make_vault(tmp_path)
    cache = tmp_path / "cache"
    build_index(vault, cache)
    fake_ollama.models = ("other-embed:latest",)
    monkeypatch.setenv("MEMWEAVE_EMBEDDING_MODEL", "ollama/other-embed")
    offline = Indexer(vault, cache, CONFIG, vector_enabled=False)
    offline.full_reindex()
    close(offline)

    restored = Indexer(vault, cache, CONFIG)
    try:
        assert restored.full_reindex().indexed == 3
        report = restored.search_report("orchid")
    finally:
        close(restored)
    assert report.mode == "hybrid"


def indexed(vault: Path) -> list[str]:
    instance = Indexer(vault, default_cache_dir(vault), CONFIG)
    try:
        return sorted(instance.indexed_paths())
    finally:
        close(instance)


def test_reindex_path_removes_deleted_and_renames_moved_notes(tmp_path, fake_ollama, cache_root):
    vault = make_vault(tmp_path)
    build_index(vault, default_cache_dir(vault))
    fake_ollama.texts.clear()

    (vault / "wiki/note0.md").unlink()
    (vault / "archive").mkdir()
    (vault / "wiki/note1.md").rename(vault / "archive/moved.md")
    result = run_cli(
        "reindex",
        "--path",
        "wiki/note0.md",
        "--path",
        "wiki/note1.md",
        "--path",
        "archive/moved.md",
        "--vault",
        vault,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == "Indexed: 1, Skipped: 0, Deleted: 2\n"
    assert indexed(vault) == ["archive/moved.md", "wiki/note2.md"]
    assert fake_ollama.texts == [], "a moved note reuses its cached embeddings"

    (vault / "wiki").rename(vault / "notes")
    result = run_cli("reindex", "--path", "wiki", "--path", "notes", "--vault", vault)
    assert result.returncode == 0, result.stderr
    assert result.stdout == "Indexed: 1, Skipped: 0, Deleted: 1\n"
    assert indexed(vault) == ["archive/moved.md", "notes/note2.md"]
