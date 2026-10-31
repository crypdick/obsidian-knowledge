"""Start index maintenance outside interactive command deadlines."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from lib.vault_index.index_lock import index_lock
from lib.vault_index.models import IndexBusyError

# NOTE: docs/CLI.md "Search health and network access" documents this deadline
# and log file. Progress is checkpointed, so a later search resumes the work.
BACKGROUND_REINDEX_TIMEOUT_SECONDS = 1800
LOG_FILENAME = "background-reindex.log"
REINDEX_REASONS = frozenset({"vector index requires reindex", "vector index unavailable"})


def index_command(vault: Path, *arguments: str) -> list[str]:
    """Return a CLI reindex invocation using this interpreter's installation."""
    return [sys.executable, "-m", "lib.vault_index.cli", "reindex", "--vault", str(vault), *arguments]


def start_background_reindex(vault: Path, cache: Path) -> bool:
    """Detach one incremental reindex; return False when an index writer already runs."""
    try:
        with index_lock(cache, exclusive=True, blocking=False):
            pass
    except IndexBusyError:
        return False
    # A racing search may also start one; the loser exits cleanly on the lock.
    with (cache / LOG_FILENAME).open("ab") as log:
        subprocess.Popen(
            index_command(vault, "--timeout-seconds", str(BACKGROUND_REINDEX_TIMEOUT_SECONDS)),
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    return True
