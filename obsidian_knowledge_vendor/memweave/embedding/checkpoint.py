"""Size embedding requests so every committed batch represents bounded work."""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable

# NOTE: docs/CLI.md "Indexing progress" documents the checkpoint interval.
CHECKPOINT_SECONDS = 5.0
INITIAL_BATCH = 4


class CheckpointBatcher:
    """Adapt request size to embedder speed; callers persist each returned batch.

    A CPU-only embedder taking seconds per chunk keeps batches small, so an
    interruption loses at most a few seconds of work. Fast embedders grow
    toward ``maximum`` by doubling.
    """

    def __init__(self, maximum: int):
        self.maximum = maximum
        self.size = min(INITIAL_BATCH, maximum)

    async def embed(
        self, batch: list[str], embed_batch: Callable[[list[str]], Awaitable[list[list[float]]]]
    ) -> list[list[float]]:
        """Embed one batch of at most ``size`` texts and adapt the next size."""
        start = time.monotonic()
        vectors = await embed_batch(batch)
        elapsed = max(time.monotonic() - start, 1e-6)
        paced = int(len(batch) * CHECKPOINT_SECONDS / elapsed)
        self.size = max(1, min(self.maximum, len(batch) * 2, paced))
        return vectors
