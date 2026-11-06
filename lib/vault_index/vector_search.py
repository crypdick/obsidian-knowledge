"""Use sqlite-vec's native nearest-neighbor scan for hybrid retrieval."""

from __future__ import annotations

import sqlite3
import struct

import aiosqlite

from obsidian_knowledge_vendor.memweave import HybridConfig
from obsidian_knowledge_vendor.memweave.search.hybrid import merge_hybrid_results
from obsidian_knowledge_vendor.memweave.search.keyword import KeywordSearch
from obsidian_knowledge_vendor.memweave.search.strategy import RawSearchRow


class IndexedHybridSearch:
    """Preserve memweave's hybrid scoring without fetching every vector into SQL."""

    def __init__(self, config: HybridConfig):
        self.config = config

    async def search(
        self,
        db: aiosqlite.Connection,
        query: str,
        query_vec: list[float] | None,
        model: str,
        limit: int,
        *,
        source_filter: str | None = None,
    ) -> list[RawSearchRow]:
        keyword = KeywordSearch()
        if query_vec is None:
            try:
                await db.execute("SELECT vec_version()")
            except sqlite3.OperationalError as exc:
                if "no such function" not in str(exc):
                    raise
                return await keyword.search(db, query, None, model, limit, source_filter=source_filter)
            raise ValueError("VectorSearch requires a query_vec (got None)")

        # NOTE: docs/ARCHITECTURE.md documents the bounded candidate pool.
        # Never fall back to exhaustive Python/JSON vector retrieval. MemWeave
        # already expands candidates before invoking this strategy.
        pool = min(4096, limit * self.config.candidate_multiplier)

        blob = struct.pack(f"<{len(query_vec)}f", *query_vec)
        params: list[object] = [blob, pool, model, source_filter or None, source_filter or None]
        # memweave normalizes stored and query vectors: L2 and cosine rank
        # identically. For unit vectors cosine = 1 - L2²/2; do not fetch each
        # selected vector again merely to recompute that score.
        # Filter inside KNN so other models/sources cannot exhaust its pool.
        sql = """
            WITH nearest AS MATERIALIZED (
                SELECT id, distance FROM chunks_vec
                WHERE embedding MATCH ? AND k = ?
                  AND id IN (
                      SELECT id FROM chunks WHERE model = ? AND (? IS NULL OR source = ?)
                  )
            )
            SELECT c.id, c.path, c.source, c.start_line, c.end_line, c.text,
                   1 - n.distance * n.distance / 2.0 AS score
            FROM nearest n JOIN chunks c ON c.id = n.id
            ORDER BY score DESC
        """
        vector_rows = []
        async with db.execute(sql, params) as cursor:
            async for row in cursor:
                chunk_id, path, source, start_line, end_line, text, score = row
                vector_rows.append(
                    RawSearchRow(
                        chunk_id=chunk_id,
                        path=path,
                        source=source,
                        start_line=start_line,
                        end_line=end_line,
                        text=text,
                        score=score,
                        vector_score=score,
                    )
                )
        keyword_rows = await keyword.search(db, query, None, model, pool, source_filter=source_filter)
        return merge_hybrid_results(
            vector_rows,
            keyword_rows,
            vector_weight=self.config.vector_weight,
            text_weight=self.config.text_weight,
            limit=limit,
        )
