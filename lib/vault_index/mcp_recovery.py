"""Own one background index repair independently of search request deadlines."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import Awaitable, Callable

from lib.vault_index.models import SearchReport

logger = logging.getLogger(__name__)
RECOVERY_TIMEOUT_SECONDS = 1800
RECOVERY_RETRY_SECONDS = 60


class IndexRecovery:
    """Coalesce stale-index searches and reap recovery work at server shutdown."""

    def __init__(self, rebuild: Callable[[], Awaitable[None]]):
        self.rebuild = rebuild
        self.task: asyncio.Task[None] | None = None
        self.retry_at = 0.0

    def request(self) -> None:
        """Schedule one repair; repeated searches neither cancel nor duplicate it."""
        if (self.task is None or self.task.done()) and time.monotonic() >= self.retry_at:
            self.task = asyncio.create_task(self._run())

    def repair_if_needed(self, report: SearchReport) -> SearchReport:
        """Keep keyword results available while repairing a stale vector lane."""
        if report.degraded_reason in {"vector index requires reindex", "vector index unavailable"}:
            self.request()
            if self.task is not None and not self.task.done():
                return report.model_copy(update={"degraded_reason": "vector index rebuilding"})
        return report

    async def _run(self) -> None:
        try:
            logger.info("Starting background vector index repair")
            await self.rebuild()
            logger.info("Background vector index repair finished")
        except (ValueError, OSError, TimeoutError):
            logger.exception("Background vector index repair failed; a later search will retry")
        finally:
            self.retry_at = time.monotonic() + RECOVERY_RETRY_SECONDS

    async def close(self) -> None:
        """Cancel and await the worker so its subprocess cleanup can finish."""
        if self.task is not None:
            self.task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.task
