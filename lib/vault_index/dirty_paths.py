"""Durable, coalesced per-file work shared by notifications and reconciliation."""

from __future__ import annotations

import sqlite3
import time
from contextlib import closing
from pathlib import Path


class DirtyPaths:
    """Track observed content and revisions separately from completed indexing."""

    def __init__(self, database: Path, *, quiet_seconds: float | int = 30):
        self.database = database
        self.quiet_seconds = quiet_seconds
        database.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(database)) as db, db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute(
                "CREATE TABLE IF NOT EXISTS pending (path TEXT PRIMARY KEY, signature TEXT NOT NULL, "
                "revision INTEGER NOT NULL, done INTEGER NOT NULL DEFAULT 0, "
                "eligible REAL NOT NULL, first_seen REAL NOT NULL)"
            )

    def mark(self, path: str, signature: str, *, now: float | int | None = None) -> int:
        """An unchanged observation never restarts the quiet period."""
        if Path(path).is_absolute() or ".." in Path(path).parts:
            raise ValueError("dirty path must be vault-relative")
        instant = time.time() if now is None else now
        with closing(sqlite3.connect(self.database)) as db, db:
            db.execute(
                "INSERT INTO pending(path,signature,revision,eligible,first_seen) VALUES(?,?,1,?,?) "
                "ON CONFLICT(path) DO UPDATE SET signature=excluded.signature, revision=revision+1, "
                "eligible=excluded.eligible, "
                "first_seen=CASE WHEN done=revision THEN excluded.first_seen ELSE first_seen END "
                "WHERE signature != excluded.signature",
                (path, signature, instant + self.quiet_seconds, instant),
            )
            return int(db.execute("SELECT revision FROM pending WHERE path=?", (path,)).fetchone()[0])

    def ready(self, *, now: float | int | None = None) -> tuple[str, int] | None:
        """Choose oldest pending file whose quiet period or retry delay elapsed."""
        with closing(sqlite3.connect(self.database)) as db:
            row = db.execute(
                "SELECT path, revision FROM pending WHERE done < revision AND eligible <= ? "
                "ORDER BY first_seen, path LIMIT 1",
                (time.time() if now is None else now,),
            ).fetchone()
        return (str(row[0]), int(row[1])) if row else None

    def current(self, path: str, revision: int) -> bool:
        with closing(sqlite3.connect(self.database)) as db:
            return (
                db.execute("SELECT 1 FROM pending WHERE path=? AND revision=?", (path, revision)).fetchone()
                is not None
            )

    def complete(self, path: str, revision: int) -> None:
        with closing(sqlite3.connect(self.database)) as db, db:
            db.execute("UPDATE pending SET done=? WHERE path=? AND revision=?", (revision, path, revision))

    def retry(self, path: str, revision: int, *, delay: float | int = 60) -> None:
        with closing(sqlite3.connect(self.database)) as db, db:
            db.execute(
                "UPDATE pending SET eligible=? WHERE path=? AND revision=?",
                (time.time() + delay, path, revision),
            )

    def pending_count(self) -> int:
        with closing(sqlite3.connect(self.database)) as db:
            return int(db.execute("SELECT count(*) FROM pending WHERE done < revision").fetchone()[0])

    def invalidate(self) -> None:
        """A new generation needs every observed file; preserve quiet deadlines."""
        with closing(sqlite3.connect(self.database)) as db, db:
            db.execute("UPDATE pending SET revision=revision+1")

    def require(self, path: str) -> None:
        """Repair missing generation work without disturbing an already pending edit."""
        with closing(sqlite3.connect(self.database)) as db, db:
            db.execute("UPDATE pending SET revision=revision+1 WHERE path=? AND done=revision", (path,))
