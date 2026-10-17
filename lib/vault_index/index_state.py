"""Read persisted vector-index readiness without constructing a store."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path


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
