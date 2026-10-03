"""Hybrid retrieval stays bounded on a populated vector cache."""

from __future__ import annotations

import asyncio
import math
import sqlite3
import struct
import time
from contextlib import closing
from pathlib import Path

import aiosqlite
import pytest
import sqlite_vec
from memweave.storage.schema import ensure_schema, ensure_vector_table

from lib.vault_index.config import VaultIndexConfig
from lib.vault_index.indexer import Indexer


def seed_cache(cache: Path, vault: Path, count: int = 6000) -> None:
    cache.mkdir()
    database = cache / "index.sqlite"

    async def schema():
        async with aiosqlite.connect(database) as connection:
            await ensure_schema(connection)
            await connection.enable_load_extension(True)
            await connection.load_extension(sqlite_vec.loadable_path())
            await ensure_vector_table(connection, 1024)

    asyncio.run(schema())
    with closing(sqlite3.connect(database)) as connection, connection:
        connection.enable_load_extension(True)
        sqlite_vec.load(connection)
        connection.executemany(
            "INSERT INTO chunks VALUES (?, ?, ?, 1, 1, ?, ?, ?, NULL, 0)",
            [
                (str(i), str(vault / f"note-{i}.md"), "memory", str(i), "ollama/bge-m3", "indexed text")
                for i in range(count)
            ],
        )
        connection.executemany(
            "INSERT INTO chunks_vec (id, embedding) VALUES (?, ?)",
            [(str(i), struct.pack("1024f", 1.0 if i == 0 else -1.0, *([0.0] * 1023))) for i in range(count)],
        )


def test_populated_cache_search_preserves_semantics_within_budget(tmp_path):
    cache = tmp_path / "cache"
    seed_cache(cache, tmp_path)
    instance = Indexer(tmp_path, cache, VaultIndexConfig(), skip_probe=True)

    async def embed_query(text):
        return [1.0, *([0.0] * 1023)]

    instance._store.embedding_provider.embed_query = embed_query
    started = time.monotonic()
    try:
        report = instance.search_report("no-keyword-match", top_k=1, allow_rebuild=False)
        elapsed = time.monotonic() - started
        assert report.mode == "hybrid"
        assert report.hits[0].path == "note-0.md"
        assert report.hits[0].score == pytest.approx(70.0)
        assert elapsed < 1.0, f"vector retrieval took {elapsed:.2f}s"
    finally:
        asyncio.run(instance._store.close())


@pytest.mark.parametrize("source_filter", [None, "memory", "sessions", "absent"])
def test_native_search_matches_exhaustive_scores_and_filters(tmp_path, source_filter):
    from memweave import HybridConfig
    from memweave.search.hybrid import HybridSearch

    from lib.vault_index.vector_search import IndexedHybridSearch

    cache = tmp_path / "cache"
    seed_cache(cache, tmp_path, count=30)
    database = cache / "index.sqlite"
    with closing(sqlite3.connect(database)) as connection, connection:
        connection.enable_load_extension(True)
        sqlite_vec.load(connection)
        connection.execute("UPDATE chunks SET model = 'other-model' WHERE id = '0'")
        connection.execute("UPDATE chunks SET source = 'sessions' WHERE id = '29'")
        for i in range(1, 29):
            cosine = -0.5 + i * 0.01
            connection.execute(
                "UPDATE chunks_vec SET embedding = ? WHERE id = ?",
                (struct.pack("1024f", cosine, math.sqrt(1 - cosine**2), *([0.0] * 1022)), str(i)),
            )
        connection.execute(
            "UPDATE chunks_vec SET embedding = ? WHERE id = '29'",
            (struct.pack("1024f", 0.6, 0.8, *([0.0] * 1022)),),
        )
        connection.execute(
            "INSERT INTO chunks_fts VALUES (?, ?, ?, ?, ?, 1, 1)",
            ("CardDAV", "29", str(tmp_path / "note-29.md"), "sessions", "ollama/bge-m3"),
        )

    async def retrieve():
        async with aiosqlite.connect(database) as connection:
            await connection.enable_load_extension(True)
            await connection.load_extension(sqlite_vec.loadable_path())
            args = (connection, "CardDAV", [1.0, *([0.0] * 1023)], "ollama/bge-m3", 1)
            expected = await HybridSearch().search(*args, source_filter=source_filter)
            actual = await IndexedHybridSearch(HybridConfig()).search(*args, source_filter=source_filter)
            assert actual == expected
            if source_filter in {None, "sessions"}:
                assert actual[0].chunk_id == "29"
                assert actual[0].vector_score == pytest.approx(0.6)
                assert actual[0].text_score > 0
            elif source_filter == "absent":
                assert actual == []
            else:
                assert actual[0].vector_score == pytest.approx(-0.22)

    asyncio.run(retrieve())


@pytest.mark.parametrize("limit", [1, 1025])
def test_missing_embedding_and_large_request_keep_existing_behavior(tmp_path, limit):
    from memweave import HybridConfig
    from memweave.search.hybrid import HybridSearch

    from lib.vault_index.vector_search import IndexedHybridSearch

    cache = tmp_path / "cache"
    seed_cache(cache, tmp_path, count=2)

    async def retrieve():
        async with aiosqlite.connect(cache / "index.sqlite") as connection:
            await connection.enable_load_extension(True)
            await connection.load_extension(sqlite_vec.loadable_path())
            strategy = IndexedHybridSearch(HybridConfig())
            with pytest.raises(ValueError, match=r"query_vec.*None"):
                await strategy.search(connection, "CardDAV", None, "ollama/bge-m3", limit)
            args = (connection, "CardDAV", [1.0, *([0.0] * 1023)], "ollama/bge-m3", limit)
            assert await strategy.search(*args) == await HybridSearch().search(*args)

    asyncio.run(retrieve())


def test_missing_vector_extension_keeps_keyword_search(tmp_path):
    from memweave import HybridConfig

    from lib.vault_index.vector_search import IndexedHybridSearch

    async def retrieve():
        async with aiosqlite.connect(tmp_path / "index.sqlite") as connection:
            await ensure_schema(connection)
            await connection.execute(
                "INSERT INTO chunks_fts VALUES ('CardDAV', '1', 'contacts.md', 'memory', 'model', 1, 1)"
            )
            rows = await IndexedHybridSearch(HybridConfig()).search(connection, "CardDAV", None, "model", 1)
            assert [row.path for row in rows] == ["contacts.md"]

    asyncio.run(retrieve())


def test_missing_embedding_does_not_hide_database_errors(tmp_path, monkeypatch):
    from memweave import HybridConfig

    from lib.vault_index.vector_search import IndexedHybridSearch

    async def retrieve():
        async with aiosqlite.connect(tmp_path / "index.sqlite") as connection:

            async def fail(sql):
                raise sqlite3.OperationalError("database is locked")

            monkeypatch.setattr(connection, "execute", fail)
            with pytest.raises(sqlite3.OperationalError, match="database is locked"):
                await IndexedHybridSearch(HybridConfig()).search(connection, "query", None, "model", 1)

    asyncio.run(retrieve())
