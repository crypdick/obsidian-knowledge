"""memweave wrapper for vault retrieval.

Provides a vault-aware interface over memweave's BM25 + FTS retrieval:
- Index-time filtering (paths matching config.index.deny_regex are skipped).
- Score rescaling (BM25 × 100 for readable digest output).
- FTS keyword search via memweave's SQLite FTS5 backend.

memweave API notes (verified against memweave source, 2026-05-09):
- Main class is ``memweave.MemWeave`` (not ``memweave.Store``).
- All public methods are async coroutines — wrapped here with asyncio.run().
- File discovery uses ``workspace_dir/memory/`` + ``extra_paths``. We leave
  ``workspace_dir/memory/`` empty and drive indexing entirely via
  ``extra_paths`` (set to the filtered vault file list on each reindex).
- Stored file paths are absolute. We convert to vault-relative on output.
- ``IndexResult`` fields: ``files_indexed``, ``files_skipped``, ``files_deleted``
  (not ``.indexed`` / ``.skipped`` as the plan assumed).
- ``status().files`` gives file count (plan assumed ``count_files()`` method).
- Deletion of stale files is handled automatically by ``store.index()``
  comparing ``extra_paths`` to the DB's stored paths.
- The ``sync.on_search=True`` default triggers an auto-reindex on every search
  call, which DELETES all stored chunks when extra_paths=[] (as a read-only
  handle would have). We always set ``sync=SyncConfig(on_search=False)`` to
  prevent this destructive auto-sync.
- Vector search requires an embedding API key. We default to
  ``VectorConfig(enabled=False)`` (FTS-only) so the wrapper works without
  credentials; production deployments with an API key can pass
  ``vector_enabled=True`` to the constructor.
- Search ``min_score`` defaults to ``0.35`` in memweave QueryConfig, which
  filters out BM25 scores on short documents. We always pass ``min_score=0.0``
  to memweave and let our own ``apply_filters`` handle thresholding.
- FTS BM25 scores for short fixture documents are near 0.0 after
  ``bm25_rank_to_score()``. ``apply_filters`` only applies config.min_score
  when explicitly set, so these tiny-score hits still surface in tests.
"""
from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from pathlib import Path

import memweave
from pydantic import BaseModel

from lib.vault_index.config import VaultIndexConfig
from lib.vault_index.filters import path_passes


class Hit(BaseModel):
    path: str
    score: float
    weight_applied: float = 1.0


@dataclass
class SyncStats:
    indexed: int
    skipped: int
    deleted: int


def _rescale(raw: float) -> float:
    """Multiply raw BM25/hybrid score by 100 for readable digest display."""
    return round(raw * 100, 1)




class Indexer:
    """Vault-aware wrapper around memweave.

    Uses memweave's FTS5 (BM25) backend for keyword retrieval. Index-time
    path filtering is applied by computing the allowed file list before each
    ``index()`` call and passing it as ``extra_paths`` — files excluded by
    config never enter the store.

    All memweave calls are async internally; this class exposes a synchronous
    interface via ``asyncio.run()``.

    A single ``MemWeave`` instance is created at construction and reused for
    all operations. ``full_reindex()`` closes and recreates it with updated
    ``extra_paths`` so memweave's deletion detection sees exactly the
    currently-allowed file set.
    """

    def __init__(
        self,
        vault_root: Path,
        cache_dir: Path,
        config: VaultIndexConfig,
        *,
        vector_enabled: bool = False,
    ):
        self.vault_root = vault_root
        self.cache_dir = cache_dir
        self.config = config
        self._vector_enabled = vector_enabled
        cache_dir.mkdir(parents=True, exist_ok=True)
        # Start with an empty-extra_paths store for read-only queries.
        # full_reindex() will replace this with the full allowed-paths store.
        self._store = memweave.MemWeave(
            self._make_config(extra_paths=[])
        )

    def _make_config(
        self,
        extra_paths: list[str],
    ) -> memweave.MemoryConfig:
        """Build a MemoryConfig for our vault-wrapper use case.

        Key non-defaults:
        - ``progress=False`` — suppress rich/spinner output.
        - ``sync.on_search=False`` — prevent auto-reindex on search, which would
          delete stored chunks when extra_paths differs from the DB state.
        - ``vector.enabled=False`` (default) — FTS-only mode; no API key needed.

        Embedding model + endpoint are read from environment variables so users
        can point memweave at a local Ollama (or any LiteLLM-compatible endpoint)
        without hardcoding:
        - ``MEMWEAVE_EMBEDDING_MODEL`` — overrides the model name
          (default: ``text-embedding-3-small``).
        - ``MEMWEAVE_EMBEDDING_API_BASE`` — sets the API base URL
          (default: ``None``, i.e. OpenAI public endpoint).
        - ``MEMWEAVE_EMBEDDING_API_KEY`` — sets the API key
          (default: ``None``, i.e. read from ``OPENAI_API_KEY`` by LiteLLM).
        """
        embedding_kwargs: dict = {}
        model = os.environ.get("MEMWEAVE_EMBEDDING_MODEL")
        if model is not None:
            embedding_kwargs["model"] = model
        api_base = os.environ.get("MEMWEAVE_EMBEDDING_API_BASE")
        if api_base is not None:
            embedding_kwargs["api_base"] = api_base
        api_key = os.environ.get("MEMWEAVE_EMBEDDING_API_KEY")
        if api_key is not None:
            embedding_kwargs["api_key"] = api_key

        return memweave.MemoryConfig(
            workspace_dir=str(self.cache_dir),
            db_path=str(self.cache_dir / "index.sqlite"),
            progress=False,
            extra_paths=extra_paths,
            embedding=memweave.EmbeddingConfig(**embedding_kwargs),
            vector=memweave.VectorConfig(enabled=self._vector_enabled),
            sync=memweave.SyncConfig(on_search=False),
        )

    def _abs_to_rel(self, abs_path: str) -> str:
        """Convert an absolute path to vault-relative. Passthrough if outside vault."""
        try:
            return str(Path(abs_path).relative_to(self.vault_root))
        except ValueError:
            return abs_path

    def row_count(self) -> int:
        """Number of files currently indexed."""
        status = asyncio.run(self._store.status())
        return status.files

    def indexed_paths(self) -> list[str]:
        """All currently-indexed paths, relative to vault_root."""
        files = asyncio.run(self._store.files())
        return [self._abs_to_rel(f.path) for f in files]

    def _allowed_vault_files(self) -> list[str]:
        """Return absolute paths of all vault .md files passing index filters."""
        allowed = []
        for abs_path in self.vault_root.rglob("*.md"):
            rel = str(abs_path.relative_to(self.vault_root))
            if path_passes(rel, self.config.index):
                allowed.append(str(abs_path))
        return allowed

    def full_reindex(self, force: bool = False) -> SyncStats:
        """Walk vault, index every markdown file matching index filters.

        Closes the current MemWeave instance and creates a new one with
        ``extra_paths`` set to the filtered file list. memweave's ``index()``
        handles hash-skip logic (unchanged files are skipped unless
        ``force=True``) and automatic deletion of stale DB entries (paths
        previously in the DB that are no longer in ``extra_paths``).
        """
        # Close the current store before opening a new one on the same DB.
        asyncio.run(self._store.close())

        allowed = self._allowed_vault_files()
        self._store = memweave.MemWeave(
            self._make_config(extra_paths=allowed)
        )
        result = asyncio.run(self._store.index(force=force))
        return SyncStats(
            indexed=result.files_indexed,
            skipped=result.files_skipped,
            deleted=result.files_deleted,
        )

    def sync(self) -> SyncStats:
        """Incremental re-index. Same as full_reindex without force."""
        return self.full_reindex(force=False)

    def search(
        self,
        query: str,
        *,
        top_k: int | None = None,
        min_score: float | None = None,
        override_digest_filter: bool = False,
    ) -> list[Hit]:
        """Run FTS retrieval; apply digest filter + weights; rescale; truncate.

        Always passes ``min_score=0.0`` to memweave so the default 0.35
        threshold (which filters out short-document BM25 scores) doesn't
        silently drop results. Score thresholding is applied by ``apply_filters``
        using ``config.min_score``.
        """
        from lib.vault_index.filters import apply_filters

        effective_top_k = top_k or self.config.top_k
        # Request more candidates than needed so apply_filters has room to filter.
        candidate_count = max(50, effective_top_k * 5)

        raw = asyncio.run(
            self._store.search(query, max_results=candidate_count, min_score=0.0)
        )
        hits = [
            Hit(path=self._abs_to_rel(r.path), score=_rescale(r.score), weight_applied=1.0)
            for r in raw
        ]

        cfg = self.config
        if top_k is not None:
            cfg = cfg.model_copy(update={"top_k": top_k})
        if min_score is not None:
            cfg = cfg.model_copy(update={"min_score": min_score})

        return apply_filters(hits, cfg, override_digest_filter=override_digest_filter)
