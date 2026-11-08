"""Read persisted vector-index readiness without constructing a store."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from contextlib import closing
from pathlib import Path

from lib.vault_index.embeddings import DEFAULT_EMBEDDING_API_BASE

DEFAULT_EMBEDDING_MODEL = "ollama/bge-m3"
DEFAULT_CHUNK_TOKENS = 320
DEFAULT_CHUNK_OVERLAP = 64
FINGERPRINT_FILENAME = "embedder-fingerprint.txt"


def embedding_settings() -> tuple[str, str, str | None]:
    return (
        os.environ.get("MEMWEAVE_EMBEDDING_MODEL", DEFAULT_EMBEDDING_MODEL),
        os.environ.get("MEMWEAVE_EMBEDDING_API_BASE", DEFAULT_EMBEDDING_API_BASE),
        os.environ.get("MEMWEAVE_EMBEDDING_API_KEY"),
    )


def embedding_fingerprint() -> str:
    """Versioned provider/model/endpoint/chunk identity; never persist credentials."""
    model, endpoint, _ = embedding_settings()
    provider = "ollama-http" if model.startswith("ollama/") else "litellm"
    identity = json.dumps([provider, model, endpoint, DEFAULT_CHUNK_TOKENS, DEFAULT_CHUNK_OVERLAP])
    digest = hashlib.sha256(identity.encode()).hexdigest()
    return f"{model}@{DEFAULT_CHUNK_TOKENS}/{DEFAULT_CHUNK_OVERLAP}#v2:{digest}"


def vector_issue(cache: Path) -> str | None:
    """One persisted-readiness contract shared by queries, workers, and MCP.

    Legacy fingerprints cannot establish endpoint identity. Rebuild them while
    retaining keyword retrieval, rather than assuming their vectors compatible.
    """
    database = cache / "index.sqlite"
    if not database.exists() or indexed_file_count(database) == 0:
        return "index not built yet"
    if rebuild_pending(database):
        return "index rebuild incomplete"
    try:
        stored = (cache / FINGERPRINT_FILENAME).read_text().strip()
    except (OSError, UnicodeError):
        return "embedding fingerprint unavailable"
    if stored == "keyword-only":
        return "vectors missing after keyword-only sync"
    current = embedding_fingerprint()
    if stored != current:
        return f"embedder changed (was {stored}, now {current})"
    if not vector_table_exists(database):
        return "vector index unavailable"
    return None


def rebuild_pending(database: Path) -> bool:
    """Return whether a resumable rebuild has not yet completed."""
    try:
        with closing(sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)) as connection:
            row = connection.execute(
                "SELECT value FROM meta WHERE key = 'memory_index_rebuild_v1'"
            ).fetchone()
    except sqlite3.Error:
        return False
    return row is not None


def vector_table_exists(database: Path) -> bool:
    """Return whether memweave's persisted vector table exists."""
    try:
        with closing(sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)) as connection:
            row = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='chunks_vec'"
            ).fetchone()
    except sqlite3.Error:
        return False
    return row is not None


def indexed_file_count(database: Path) -> int | None:
    """Return the number of indexed files, or None when the index is unreadable."""
    try:
        with closing(sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)) as connection:
            return int(connection.execute("SELECT count(*) FROM files").fetchone()[0])
    except sqlite3.Error:
        return None
