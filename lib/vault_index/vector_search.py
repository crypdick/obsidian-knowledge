"""Use sqlite-vec's native nearest-neighbor scan for hybrid retrieval."""

from __future__ import annotations

import sqlite3
import struct
from collections.abc import Callable

import aiosqlite

from obsidian_knowledge_vendor.memweave import HybridConfig
from obsidian_knowledge_vendor.memweave.search.hybrid import merge_hybrid_results
from obsidian_knowledge_vendor.memweave.search.keyword import KeywordSearch
from obsidian_knowledge_vendor.memweave.search.strategy import RawSearchRow


class CandidateBudgetError(RuntimeError):
    """Bounded chunk retrieval cannot establish an eligible document pool."""


class IndexedHybridSearch:
    """Preserve memweave's hybrid scoring without fetching every vector into SQL."""

    def __init__(self, config: HybridConfig, keep: Callable[[str], bool] = lambda _path: True):
        self.config = config
        self.keep = keep

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
        # Never fall back to exhaustive Python/JSON vector retrieval. Indexer
        # disables vendor expansion; this strategy owns chunk-pool growth.
        pool = min(4096, limit * self.config.candidate_multiplier)

        while True:
            vector_rows = await self.vector_rows(db, query_vec, model, pool, source_filter)
            keyword_rows = await keyword.search(db, query, None, model, pool, source_filter=source_filter)
            # Eligibility and document identity precede both strategy and vendor
            # cutoffs. Expand only when excluded/repeated chunks consumed the pool.
            merged = merge_hybrid_results(
                [row for row in vector_rows if self.keep(row.path)],
                [row for row in keyword_rows if self.keep(row.path)],
                vector_weight=self.config.vector_weight,
                text_weight=self.config.text_weight,
            )
            documents: dict[str, RawSearchRow] = {}
            for row in merged:
                documents.setdefault(row.path, row)
            if len(documents) >= min(limit, 4096) or (len(vector_rows) < pool and len(keyword_rows) < pool):
                return list(documents.values())[:limit]
            if pool == 4096:
                raise CandidateBudgetError("eligible document candidate budget exhausted")
            pool = min(4096, pool * 2)

    @staticmethod
    async def vector_rows(
        db: aiosqlite.Connection, query_vec: list[float], model: str, pool: int, source_filter: str | None
    ) -> list[RawSearchRow]:
        blob = struct.pack(f"<{len(query_vec)}f", *query_vec)
        params: list[object] = [blob, pool, model, source_filter or None, source_filter or None]
        # Keep eligibility on the covering index, never scan JSON embeddings.
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
        return vector_rows
