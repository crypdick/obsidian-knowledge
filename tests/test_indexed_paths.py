"""Path enumeration stays independent of stored chunk and embedding payloads."""

import asyncio
import sqlite3
from contextlib import closing

import pytest

from lib.vault_index.config import VaultIndexConfig
from lib.vault_index.indexer import Indexer


def test_indexed_paths_reads_only_file_metadata(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "note.md").write_text("# Indexed note\n\nOrchid greenhouse.\n")
    cache = tmp_path / "cache ?#"
    instance = Indexer(vault, cache, VaultIndexConfig(), vector_enabled=False)
    try:
        instance.full_reindex()
    finally:
        asyncio.run(instance._store.close())

    # Empty/deleted notes still have tracked file records; paths outside the
    # vault retain the existing passthrough contract.
    with closing(sqlite3.connect(cache / "index.sqlite")) as connection, connection:
        connection.executemany(
            "INSERT INTO files VALUES (?, 'memory', 'hash', 0, 0)",
            [(str(vault / "empty.md"),), (str(tmp_path / "outside.md"),)],
        )

    reads = []
    connect = sqlite3.connect

    def track_connect(*args, **kwargs):
        connection = connect(*args, **kwargs)

        def authorize(action, table, column, _database, _trigger):
            if action == sqlite3.SQLITE_READ:
                reads.append((table, column))
            return sqlite3.SQLITE_OK

        connection.set_authorizer(authorize)
        return connection

    monkeypatch.setattr(sqlite3, "connect", track_connect)
    instance = Indexer(vault, cache, VaultIndexConfig(), vector_enabled=False)
    try:
        assert sorted(instance.indexed_paths()) == sorted(
            ["empty.md", "note.md", str(tmp_path / "outside.md")]
        )
    finally:
        asyncio.run(instance._store.close())
    assert ("files", "path") in reads
    assert not any(table == "chunks" for table, _column in reads), reads


def test_indexed_paths_before_first_build(tmp_path):
    cache = tmp_path / "cache"
    instance = Indexer(tmp_path, cache, VaultIndexConfig(), vector_enabled=False)
    try:
        assert instance.indexed_paths() == []
    finally:
        asyncio.run(instance._store.close())


def test_indexed_paths_does_not_hide_broken_database(tmp_path):
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "index.sqlite").write_text("broken SQLite database")
    instance = Indexer(tmp_path, cache, VaultIndexConfig(), vector_enabled=False)
    try:
        with pytest.raises(sqlite3.DatabaseError):
            instance.indexed_paths()
    finally:
        asyncio.run(instance._store.close())
