"""Application coordination for vault index writers and maintenance."""

from __future__ import annotations

import contextlib
import fcntl
from collections.abc import Iterator
from pathlib import Path

from lib.vault_index.models import IndexBusyError


@contextlib.contextmanager
def index_lock(cache_dir: Path, *, exclusive: bool, blocking: bool = False) -> Iterator[None]:
    """Hold the per-vault SQLite access lock.

    memweave uses one SQLite DB per vault cache. Reindex/sync are writers and
    must be exclusive. Read-only searches do not acquire this lock: SQLite WAL
    provides committed snapshots for concurrent keyword and vector retrieval.
    Shared mode remains available for maintenance callers. The worker publishes
    rebuild generations separately. See docs/MCP.md's search contract.
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    lock_path = cache_dir / ".index.sqlite.lock"
    mode = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
    if not blocking:
        mode |= fcntl.LOCK_NB
    with open(lock_path, "w") as lock_f:
        try:
            fcntl.flock(lock_f.fileno(), mode)
        except BlockingIOError as exc:
            raise IndexBusyError(
                "vault index is busy: another operation holds the index lock; retry after it completes"
            ) from exc
        try:
            yield
        finally:
            fcntl.flock(lock_f.fileno(), fcntl.LOCK_UN)
