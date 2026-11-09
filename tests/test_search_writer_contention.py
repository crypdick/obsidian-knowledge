"""Public CLI/MCP searches preserve vector consistency during indexing."""

from __future__ import annotations

import asyncio
import fcntl
import json
import sqlite3
import subprocess
import sys
from contextlib import closing

import pytest
import sqlite_vec

from lib.vault_index.config import VaultIndexConfig
from lib.vault_index.index_generations import publish_generation
from lib.vault_index.indexer import Indexer, default_cache_dir
from lib.vault_index.mcp_server import create_server


@pytest.fixture
def vector_vault(tmp_path, monkeypatch, fake_ollama):
    monkeypatch.setenv("OBSIDIAN_KNOWLEDGE_CACHE_ROOT", str(tmp_path / "cache"))
    (tmp_path / "wiki").mkdir()
    (tmp_path / "wiki/orchid.md").write_text("# Orchid\nPurple greenhouse orchids\n")
    root = default_cache_dir(tmp_path)
    cache = root / "generation-a"
    instance = Indexer(tmp_path, cache, VaultIndexConfig(), skip_probe=True)
    instance.full_reindex()
    asyncio.run(instance._store.close())
    publish_generation(root, cache)
    fake_ollama.requests = 0
    return tmp_path, cache, fake_ollama


def test_cli_hybrid_reads_committed_index_during_uncommitted_write(vector_vault):
    vault, cache, endpoint = vector_vault
    with (
        closing(sqlite3.connect(cache / "index.sqlite")) as writer,
        (cache / ".index.sqlite.lock").open("w") as lock,
    ):
        writer.enable_load_extension(True)
        sqlite_vec.load(writer)
        writer.execute("BEGIN IMMEDIATE")
        writer.execute("DELETE FROM chunks_vec")
        writer.execute("DELETE FROM chunks")
        writer.execute("DELETE FROM chunks_fts")
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "lib.vault_index.cli",
                "search",
                "greenhouse",
                "--vault",
                str(vault),
                "--json",
            ],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    assert result.returncode == 0
    report = json.loads(result.stdout)
    assert report["mode"] == "hybrid"
    assert report["hits"][0]["path"] == "wiki/orchid.md"
    assert "timed out" not in result.stderr
    assert endpoint.requests == 1


def test_mcp_hybrid_ignores_writer_application_lock(vector_vault):
    vault, cache, endpoint = vector_vault

    async def exercise():
        server = create_server(vault)
        with (cache / ".index.sqlite.lock").open("w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            result = await asyncio.wait_for(
                server.call_tool("vault_search", {"query": "greenhouse"}), timeout=15
            )
            assert result[1]["mode"] == "hybrid"
            assert result[1]["hits"][0]["path"] == "wiki/orchid.md"
            assert endpoint.requests == 1
        result = await server.call_tool("vault_search", {"query": "greenhouse", "top_k": 1})
        assert result[1]["mode"] == "hybrid"
        assert result[1]["degraded_reason"] is None
        assert [hit["path"] for hit in result[1]["hits"]] == ["wiki/orchid.md"]
        assert endpoint.requests == 2

    asyncio.run(exercise())


def test_search_bounds_slow_query_embedding(vector_vault, monkeypatch):
    vault, _cache, endpoint = vector_vault
    endpoint.delay = 10
    monkeypatch.setenv("OBSIDIAN_KNOWLEDGE_SEARCH_TTL_SECONDS", "4")
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "lib.vault_index.cli",
            "search",
            "greenhouse",
            "--vault",
            str(vault),
            "--json",
        ],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert endpoint.requests == 1
    assert result.returncode == 0
    report = json.loads(result.stdout)
    assert report["mode"] == "keyword"
    assert report["hits"][0]["path"] == "wiki/orchid.md"
    assert "budget" in report["degraded_reason"]


@pytest.mark.parametrize("flag", ["--no-wait", "--no-rebuild"])
def test_removed_search_flags_are_rejected(tmp_path, flag):
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "lib.vault_index.cli",
            "search",
            "query",
            "--vault",
            str(tmp_path),
            flag,
        ],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert result.returncode == 2
    assert f"unrecognized arguments: {flag}" in result.stderr
    assert result.stdout == ""


def test_hybrid_snapshot_survives_writer_commit(vector_vault):
    vault, cache, _endpoint = vector_vault
    reader = Indexer(vault, cache, VaultIndexConfig(), skip_probe=True)

    async def exercise():
        store = reader._store
        try:
            await store._ensure_db(read_only=True)
            # Establish the snapshot before a separate writer commits deletions.
            cursor = await store._db.execute("SELECT count(*) FROM chunks")
            assert (await cursor.fetchone())[0] > 0
            with closing(sqlite3.connect(cache / "index.sqlite")) as writer, writer:
                writer.enable_load_extension(True)
                sqlite_vec.load(writer)
                writer.execute("DELETE FROM chunks_vec")
                writer.execute("DELETE FROM chunks")
                writer.execute("DELETE FROM chunks_fts")
            old = await store.search("greenhouse", min_score=0.0)
            assert [hit.path for hit in old] == [str(vault / "wiki/orchid.md")]
            await store.close()
            assert await store.search("greenhouse", min_score=0.0) == []
        finally:
            await store.close()

    asyncio.run(exercise())


def test_sql_uses_callers_deadline_and_next_search_clears_it(vector_vault):
    import time

    from obsidian_knowledge_vendor.memweave import SearchError

    vault, cache, _endpoint = vector_vault
    store = Indexer(vault, cache, VaultIndexConfig(), skip_probe=True)._store

    class SlowQuery:
        async def search(self, db, *args, **kwargs):
            await db.execute(
                "WITH RECURSIVE n(x) AS (VALUES(1) UNION ALL SELECT x+1 FROM n WHERE x<100000000) "
                "SELECT sum(x) FROM n"
            )
            return []

    async def exercise():
        store.register_strategy("slow", SlowQuery())
        try:
            with pytest.raises(SearchError, match="interrupted"):
                await store.search("greenhouse", strategy="slow", deadline=time.monotonic() + 0.05)
            assert await store.search("greenhouse", min_score=0.0)
        finally:
            await store.close()

    asyncio.run(exercise())
