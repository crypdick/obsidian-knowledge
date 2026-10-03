"""Use sqlite-vec's native nearest-neighbor scan for hybrid retrieval."""

from __future__ import annotations

import sqlite3
import struct

import aiosqlite
from memweave import HybridConfig
from memweave.search.hybrid import HybridSearch, merge_hybrid_results
from memweave.search.keyword import KeywordSearch
from memweave.search.strategy import RawSearchRow


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

        # NOTE: docs/ARCHITECTURE.md documents normalization and the k ceiling.
        # Match HybridSearch's backend pool. sqlite-vec caps native k at 4096;
        # unusually large requests retain memweave's exhaustive behavior.
        fallback = HybridSearch(vector_weight=self.config.vector_weight, text_weight=self.config.text_weight)
        pool = limit * fallback.candidate_multiplier
        if pool > 4096:
            return await fallback.search(db, query, query_vec, model, limit, source_filter=source_filter)

        blob = struct.pack(f"<{len(query_vec)}f", *query_vec)
        params: list[object] = [blob, pool, model, source_filter or None, source_filter or None, blob]
        # memweave normalizes stored and query vectors: L2 and cosine rank
        # identically. Compute original cosine scores on the bounded pool.
        # Filter inside KNN so other models/sources cannot exhaust its pool.
        sql = """
            WITH nearest AS MATERIALIZED (
                SELECT id, embedding, distance FROM chunks_vec
                WHERE embedding MATCH ? AND k = ?
                  AND id IN (
                      SELECT id FROM chunks WHERE model = ? AND (? IS NULL OR source = ?)
                  )
            )
            SELECT c.id, c.path, c.source, c.start_line, c.end_line, c.text,
                   1 - vec_distance_cosine(n.embedding, ?) AS score
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


class KeywordOnlyEmbeddingProvider:
    """Keep memweave's indexing pipeline offline when vectors are disabled.

    memweave 0.2 still calls its provider with vector.enabled=False. Empty
    vectors retain chunks and FTS entries without caching fake embeddings.
    """

    async def embed_query(self, text: str) -> list[float]:
        return []

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [[] for _ in texts]
