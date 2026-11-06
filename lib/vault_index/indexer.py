"""memweave wrapper for vault retrieval.

Hybrid retrieval over a vault: BM25 (FTS5) + dense vectors (Ollama/local
embeddings via LiteLLM), fused by memweave. Vector lane is on by default;
the wrapper probes Ollama at construction and degrades to FTS-only if the
embedding endpoint is unreachable or the chosen model isn't pulled.

memweave API notes (verified against memweave source, 2026-05-09):
- Main class is ``memweave.MemWeave`` (not ``memweave.Store``).
- All public methods are async coroutines — wrapped here with asyncio.run().
- File discovery uses ``workspace_dir/memory/`` + ``extra_paths``. We leave
  ``workspace_dir/memory/`` empty and drive indexing entirely via
  ``extra_paths`` (set to the filtered vault file list on each reindex).
- Stored file paths are absolute. We convert to vault-relative on output.
- ``IndexResult`` fields: ``files_indexed``, ``files_skipped``, ``files_deleted``.
- ``status().files`` gives file count.
- Deletion of stale files is handled by ``store.index()`` comparing
  ``extra_paths`` to the DB's stored paths.
- ``sync.on_search=True`` (memweave default) triggers an auto-reindex on every
  search, which DELETES all stored chunks when extra_paths=[]. We always set
  ``sync=SyncConfig(on_search=False)`` to prevent destructive auto-sync.
- Search ``min_score`` defaults to 0.35 in memweave QueryConfig. We pass 0.0
  and let ``apply_filters`` handle thresholding.

Embedding defaults (this wrapper):
- Model: ``ollama/bge-m3`` (8192-token context, multilingual, ~2.3GB).
  Picked over mxbai-embed-large because mxbai's 512-token context overran
  on long uninterrupted paragraphs (logged in changelog 2026-05-09).
- API base: ``http://127.0.0.1:11434`` (Ollama default).
- API key: empty placeholder (LiteLLM/Ollama doesn't require one).
- Chunking: tokens=320, overlap=64 — well under bge-m3's 8192 ceiling, and
  also safe if a user swaps in a 512-ctx model later.
- Override any of the above via ``MEMWEAVE_EMBEDDING_MODEL``,
  ``MEMWEAVE_EMBEDDING_API_BASE``, ``MEMWEAVE_EMBEDDING_API_KEY``.

Fail-soft behavior: ``vector_enabled=True`` by default. On construction we do
a quick HTTP probe of the Ollama tags endpoint; if it fails or the chosen
model isn't listed, we silently flip vector off for this process and surface
the reason via ``self.vector_status``. The doctor SessionStart hook reads
the same probe and prints a one-line reminder.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import os
import re
import sqlite3
from collections.abc import Callable
from contextlib import closing
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Any

import platformdirs

from lib.vault_index.config import VaultIndexConfig
from lib.vault_index.embeddings import DEFAULT_EMBEDDING_API_BASE, make_embedding_provider
from lib.vault_index.embeddings import ollama_probe as _ollama_probe
from lib.vault_index.filters import path_passes
from lib.vault_index.index_generations import active_cache
from lib.vault_index.index_lock import index_lock
from lib.vault_index.index_state import indexed_file_count, rebuild_pending, vector_table_exists
from lib.vault_index.models import Hit, IndexBusyError, Progress, SearchReport
from lib.vault_index.snippets import with_snippets
from lib.vault_index.vault_listing import visible_name
from lib.vault_index.vector_search import IndexedHybridSearch
from obsidian_knowledge_vendor import memweave

# Local embeddings do not need a public model-pricing download. LiteLLM reads
# this at its first lazy import; preserve an explicit operator override.
os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")

DEFAULT_EMBEDDING_MODEL = "ollama/bge-m3"
DEFAULT_CHUNK_TOKENS = 320
DEFAULT_CHUNK_OVERLAP = 64
FINGERPRINT_FILENAME = "embedder-fingerprint.txt"
APP_NAME = "obsidian-knowledge"
CACHE_ROOT_ENV = "OBSIDIAN_KNOWLEDGE_CACHE_ROOT"
SANDBOX_CACHE_ROOT = Path("/tmp") / "obsidian-knowledge-cache"


def _cache_base_dir() -> Path:
    """Return the preferred cache base; Indexer falls back only if creation fails."""
    cache_root = os.environ.get(CACHE_ROOT_ENV)
    if cache_root:
        return Path(cache_root).expanduser() / APP_NAME

    return Path(platformdirs.user_cache_dir(APP_NAME))


def default_cache_dir(vault_root: Path) -> Path:
    """Per-host, per-vault cache directory outside the vault.

    Returns ``<XDG_CACHE_HOME or ~/.cache>/obsidian-knowledge/<vault-key>/``
    on Linux and ``~/Library/Caches/obsidian-knowledge/<vault-key>/`` on macOS.
    The vault-key combines the directory's basename with an 8-char hash of its
    absolute path so two vaults with the same dir name (e.g. ``obsidian/``
    on different machines or in different parents) never collide.

    Storing the cache outside the vault eliminates the Syncthing-conflict risk
    entirely: each host owns its own embeddings DB, no replication, no race.
    """
    abs_path = str(vault_root.resolve())
    digest = hashlib.sha256(abs_path.encode()).hexdigest()[:8]
    safe_name = re.sub(r"[^a-zA-Z0-9._-]", "-", vault_root.resolve().name) or "vault"
    return _cache_base_dir() / f"{safe_name}-{digest}"


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
        vector_enabled: bool = True,
        skip_probe: bool = False,
    ):
        self.vault_root = vault_root
        cache_dir = active_cache(cache_dir)
        self.cache_dir = cache_dir
        self.config = config
        self._vector_enabled_requested = vector_enabled
        self._vector_enabled = vector_enabled
        self.vector_status = "disabled-by-caller"
        try:
            cache_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            cache_dir = SANDBOX_CACHE_ROOT / APP_NAME / cache_dir.name
            cache_dir.mkdir(parents=True, exist_ok=True)
            self.cache_dir = cache_dir

        if vector_enabled and not skip_probe:
            model, api_base, _ = self._embedding_settings()
            ok, msg = _ollama_probe(api_base, model)
            self.vector_status = msg
            if not ok:
                self._vector_enabled = False

        # Why persisted vectors cannot serve searches yet, or None when ready.
        # Search never repairs this inline; the independent worker owns updates.
        self.vector_issue = self._vector_issue() if self._vector_enabled else None

        # Start with an empty-extra_paths store for read-only queries.
        # full_reindex() will replace this with the full allowed-paths store.
        self._store = self._make_store(extra_paths=[])

    @property
    def vector_enabled(self) -> bool:
        return self._vector_enabled

    def _make_store(self, extra_paths: list[str]) -> memweave.MemWeave:
        config = self._make_config(extra_paths=extra_paths)
        store = memweave.MemWeave(
            config,
            embedding_provider=make_embedding_provider(config.embedding, enabled=self._vector_enabled),
        )
        if self._vector_enabled:
            store.register_strategy("hybrid", IndexedHybridSearch(config.query.hybrid))
        return store

    def _embedder_fingerprint(self) -> str:
        """Stable string identifying the current embedding setup.

        Format: ``<model>@<chunk_tokens>/<chunk_overlap>``. Any change to
        model name or chunking parameters invalidates the existing index
        because chunk boundaries and vector dimensions may both shift.
        """
        model, _api_base, _ = self._embedding_settings()
        return f"{model}@{DEFAULT_CHUNK_TOKENS}/{DEFAULT_CHUNK_OVERLAP}"

    def _fingerprint_path(self) -> Path:
        return self.cache_dir / FINGERPRINT_FILENAME

    def _read_stored_fingerprint(self) -> str | None:
        try:
            return self._fingerprint_path().read_text().strip()
        except OSError:
            return None

    def _write_fingerprint(self, *, indexed: int) -> None:
        # An offline sync that indexed files leaves their chunks without
        # vectors; mark it so the next online sync is reported as catching up.
        if self._vector_enabled:
            fingerprint = self._embedder_fingerprint()
        elif indexed:
            fingerprint = "keyword-only"
        else:
            return
        with contextlib.suppress(OSError):
            self._fingerprint_path().write_text(fingerprint)

    def _vector_issue(self) -> str | None:
        """Explain why the persisted vector index cannot serve searches yet.

        memweave owns rebuild decisions; this only reports readiness. A new or
        interrupted first build is not an embedder change, so name it apart.
        """
        db = self.cache_dir / "index.sqlite"
        if not db.exists() or indexed_file_count(db) == 0:
            return "index not built yet"
        if rebuild_pending(db):
            return "index rebuild incomplete"
        stored = self._read_stored_fingerprint()
        if stored is None:
            # Pre-fingerprint caches with a vector table remain usable.
            return None if self._vector_table_exists(db) else "index not built yet"
        if stored == "keyword-only":
            return "vectors missing after keyword-only sync"
        current = self._embedder_fingerprint()
        if stored != current:
            return f"embedder changed (was {stored}, now {current})"
        if not self._vector_table_exists(db):
            return "vector index unavailable"
        return None

    @staticmethod
    def _vector_table_exists(db_path: Path) -> bool:
        """Return True when the cache already contains memweave's vector table."""
        return vector_table_exists(db_path)

    @staticmethod
    def _embedding_settings() -> tuple[str, str, str | None]:
        """Resolve (model, api_base, api_key) from env with bge-m3/Ollama defaults."""
        model = os.environ.get("MEMWEAVE_EMBEDDING_MODEL", DEFAULT_EMBEDDING_MODEL)
        api_base = os.environ.get("MEMWEAVE_EMBEDDING_API_BASE", DEFAULT_EMBEDDING_API_BASE)
        api_key = os.environ.get("MEMWEAVE_EMBEDDING_API_KEY")
        return model, api_base, api_key

    def _make_config(
        self,
        extra_paths: list[str],
    ) -> memweave.MemoryConfig:
        """Build a MemoryConfig for our vault-wrapper use case.

        Key non-defaults:
        - ``progress=False`` — suppress rich/spinner output.
        - ``sync.on_search=False`` — prevent auto-reindex on search.
        - ``vector.enabled`` — driven by the constructor-resolved value
          (probe may have flipped it off).
        - ``chunking`` — 320/64 (vs memweave default 400/80) so even a
          512-token-context model can't overrun.
        - ``embedding`` — defaults to ``ollama/bge-m3`` at
          ``http://127.0.0.1:11434``. Override via ``MEMWEAVE_EMBEDDING_MODEL``,
          ``MEMWEAVE_EMBEDDING_API_BASE``, ``MEMWEAVE_EMBEDDING_API_KEY``.
        """
        model, api_base, api_key = self._embedding_settings()
        embedding_kwargs: dict[str, Any] = {"model": model, "api_base": api_base}
        if api_key is not None:
            embedding_kwargs["api_key"] = api_key

        return memweave.MemoryConfig(
            workspace_dir=str(self.cache_dir),
            db_path=str(self.cache_dir / "index.sqlite"),
            progress=False,
            extra_paths=extra_paths,
            embedding=memweave.EmbeddingConfig(**embedding_kwargs),
            chunking=memweave.ChunkingConfig(tokens=DEFAULT_CHUNK_TOKENS, overlap=DEFAULT_CHUNK_OVERLAP),
            vector=memweave.VectorConfig(enabled=self._vector_enabled),
            sync=memweave.SyncConfig(on_search=False),
        )

    def _abs_to_rel(self, abs_path: str) -> str:
        """Convert an absolute path to vault-relative. Passthrough if outside vault."""
        try:
            return str(Path(abs_path).relative_to(self.vault_root))
        except ValueError:
            return abs_path

    @staticmethod
    def _safe_fts_query(query: str) -> str:
        """Build a conservative FTS5 query from user text."""
        terms = re.findall(r"[\w-]+", query)
        return " OR ".join(f'"{term.replace(chr(34), chr(34) * 2)}"' for term in terms)

    def _with_snippets(self, hits: list[Hit], query: str) -> list[Hit]:
        return with_snippets(self.vault_root, hits, query)

    def _sqlite_fts_search(
        self, query: str, candidate_count: int, keep: Callable[[str], bool] = lambda _path: True
    ) -> list[Hit]:
        """Use the persisted FTS table directly when vector retrieval is degraded.

        memweave can still touch vector/litellm machinery during search even
        after the Ollama probe disables vectors. In sandboxed Codex sessions
        localhost access is denied, so the degraded path must avoid memweave's
        search stack entirely and query SQLite FTS directly.
        """
        db_path = self.cache_dir / "index.sqlite"
        if not db_path.exists():
            return []

        def run(match_query: str) -> dict[str, float]:
            # Filter paths while reading rather than after a LIMIT: otherwise
            # many matching chunks outside ``keep`` can hide every kept path.
            best_by_path: dict[str, float] = {}
            with closing(sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)) as conn:
                rows = conn.execute(
                    """
                    SELECT path, -bm25(chunks_fts) AS score
                    FROM chunks_fts
                    WHERE chunks_fts MATCH ?
                    ORDER BY bm25(chunks_fts)
                    """,
                    (match_query,),
                )
                for path, score in rows:
                    rel = self._abs_to_rel(path)
                    if rel not in best_by_path and keep(rel):
                        best_by_path[rel] = score  # rows arrive best-first
                        if len(best_by_path) == candidate_count:
                            break
            return best_by_path

        try:
            best_by_path = run(query)
        except sqlite3.DatabaseError as exc:
            if "database is locked" in str(exc).lower():
                raise IndexBusyError(f"vault index is busy: {exc}") from exc
            safe_query = self._safe_fts_query(query)
            if not safe_query:
                return []
            try:
                best_by_path = run(safe_query)
            except sqlite3.DatabaseError as exc:
                if "database is locked" in str(exc).lower():
                    raise IndexBusyError(f"vault index is busy: {exc}") from exc
                return []

        return [
            Hit(path=path, score=round(score, 1), weight_applied=1.0) for path, score in best_by_path.items()
        ]

    def row_count(self) -> int:
        """Number of files currently indexed."""
        status = asyncio.run(self._store.status())
        return status.files

    def indexed_paths(self) -> list[str]:
        """All currently-indexed paths, relative to vault_root."""
        database = self.cache_dir / "index.sqlite"
        if not database.exists():
            return []
        # MemWeave.files() loads and decodes every chunk's JSON embedding to
        # count chunks. Path-only refresh bookkeeping needs only the files table.
        with closing(sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)) as connection:
            return [self._abs_to_rel(path) for (path,) in connection.execute("SELECT path FROM files")]

    def _allowed_vault_files(self) -> list[str]:
        """Return absolute paths of all vault .md files passing index filters, digest first."""
        allowed = []
        for abs_path in self.vault_root.rglob("*.md"):
            rel = str(abs_path.relative_to(self.vault_root))
            if path_passes(rel, self.config.index):
                allowed.append((not path_passes(rel, self.config.digest), rel, str(abs_path)))
        # Index digest notes first so a slow first build or rebuild makes the
        # notes searched by default available earliest.
        return [abs_path for _later, _rel, abs_path in sorted(allowed)]

    def full_reindex(
        self, force: bool = False, *, blocking: bool = False, progress: Progress | None = None
    ) -> SyncStats:
        """Walk vault, index every markdown file matching index filters.

        Closes the current MemWeave instance and creates a new one with
        ``extra_paths`` set to the filtered file list. memweave's ``index()``
        handles hash-skip logic (unchanged files are skipped unless
        ``force=True``) and automatic deletion of stale DB entries (paths
        previously in the DB that are no longer in ``extra_paths``).

        Writes the embedder fingerprint after a successful run so the next
        Indexer init can detect a model change and auto-rebuild.
        """
        with index_lock(self.cache_dir, exclusive=True, blocking=blocking):
            return self._full_reindex_unlocked(force=force, progress=progress)

    def _full_reindex_unlocked(self, force: bool = False, *, progress: Progress | None = None) -> SyncStats:
        """Run memweave index assuming the caller owns the exclusive lock."""
        # Close the current store before opening a new one on the same DB.
        asyncio.run(self._store.close())

        allowed = self._allowed_vault_files()
        self._store = self._make_store(extra_paths=allowed)
        result = asyncio.run(self._store.index(force=force, progress_callback=progress))
        self._write_fingerprint(indexed=result.files_indexed)
        self.vector_issue = self._vector_issue() if self._vector_enabled else None
        return SyncStats(
            indexed=result.files_indexed,
            skipped=result.files_skipped,
            deleted=result.files_deleted,
        )

    def index_paths(self, rel_paths: list[str]) -> SyncStats:
        """Bring specific vault files or folders up to date without walking the vault.

        Existing allowed notes are indexed (hash-skipped, reusing cached chunk
        embeddings, so a moved note embeds nothing new). Index entries at or
        under a path that is now missing or excluded are removed, which keeps
        deletes and moves consistent. Raises ``IndexBusyError`` instead of
        waiting for another index writer.
        """
        if not self._vector_enabled:
            raise IndexBusyError(f"vector embeddings unavailable ({self.vector_status})")
        if self.vector_issue is not None:
            raise IndexBusyError(f"vector index not ready ({self.vector_issue})")
        indexed = skipped = deleted = 0
        with index_lock(self.cache_dir, exclusive=True, blocking=False):
            stored = self.indexed_paths()
            for rel in rel_paths:
                root = self.vault_root / rel
                present = sorted(root.rglob("*.md")) if root.is_dir() else [root] if root.is_file() else []
                keep = {str(path.relative_to(self.vault_root)) for path in present}
                keep = {path for path in keep if path_passes(path, self.config.index)}
                for path in sorted(keep):
                    result = asyncio.run(self._store.add(self.vault_root / path))
                    indexed += result.files_indexed
                    skipped += result.files_skipped
                for path in stored:
                    if (path == rel or path.startswith(f"{rel.rstrip('/')}/")) and path not in keep:
                        deleted += asyncio.run(self._store.remove(self.vault_root / path))
        return SyncStats(indexed=indexed, skipped=skipped, deleted=deleted)

    async def index_settled_path(self, relative: str) -> None:
        """Commit one settled file, rolling back interrupted or superseded work."""
        path = self.vault_root / relative
        if not path.resolve().is_relative_to(self.vault_root.resolve()):
            raise ValueError("index path escapes vault")
        try:
            with index_lock(self.cache_dir, exclusive=True, blocking=False):
                if (
                    path.is_file()
                    and all(visible_name(part) for part in Path(relative).parts)
                    and path_passes(relative, self.config.index)
                ):
                    await self._store.add(path, force=True)
                else:
                    await self._store.remove(path)
                self._write_fingerprint(indexed=1)
        finally:
            await self._store.close()

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
        wait_for_writer: bool = True,
    ) -> list[Hit]:
        """Return ranked hits; see search_report for retrieval metadata."""
        return self.search_report(
            query,
            top_k=top_k,
            min_score=min_score,
            override_digest_filter=override_digest_filter,
            wait_for_writer=wait_for_writer,
        ).hits

    def _retrieve(self, query: str, candidate_count: int):
        try:
            # NOTE: docs/CLI.md "Search health and network access" documents
            # bounded semantic retrieval over committed read-only snapshots.
            try:
                command_budget = int(os.environ.get("OBSIDIAN_KNOWLEDGE_SEARCH_TTL_SECONDS", "30"))
            except ValueError:
                command_budget = 30
            semantic_budget = min(5.0, command_budget / 2) if command_budget > 0 else 5.0

            async def bounded_search():
                try:
                    await self._store.close()
                    return await asyncio.wait_for(
                        self._store.search(query, max_results=candidate_count, min_score=0.0),
                        timeout=semantic_budget,
                    )
                finally:
                    await self._store.close()

            return asyncio.run(bounded_search())
        except (sqlite3.OperationalError, memweave.StorageError) as exc:
            if "database is locked" in str(exc).lower():
                raise IndexBusyError(f"vault index is busy: {exc}") from exc
            raise

    def search_report(
        self,
        query: str,
        *,
        top_k: int | None = None,
        min_score: float | None = None,
        override_digest_filter: bool = False,
        wait_for_writer: bool = True,
    ) -> SearchReport:
        """Run retrieval and report its actual mode, including query fallbacks.

        Always passes ``min_score=0.0`` to memweave so the default 0.35
        threshold (which filters out short-document BM25 scores) doesn't
        silently drop results. Score thresholding is applied by ``apply_filters``
        using ``config.min_score``.
        """
        from lib.vault_index.filters import apply_filters

        effective_top_k = top_k or self.config.top_k
        # Request more candidates than needed so apply_filters has room to filter.
        candidate_count = max(50, effective_top_k * 5)

        def filtered(hits: list[Hit]) -> list[Hit]:
            cfg = self.config
            if top_k is not None:
                cfg = cfg.model_copy(update={"top_k": top_k})
            if min_score is not None:
                cfg = cfg.model_copy(update={"min_score": min_score})
            return apply_filters(hits, cfg, override_digest_filter=override_digest_filter)

        def keyword_report(reason: str) -> SearchReport:
            keep = (
                (lambda _path: True)
                if override_digest_filter
                else partial(path_passes, filt=self.config.digest)
            )
            hits = self._with_snippets(filtered(self._sqlite_fts_search(query, candidate_count, keep)), query)
            hidden = (
                0 if hits or override_digest_filter else len(self._sqlite_fts_search(query, candidate_count))
            )
            return SearchReport(
                mode="keyword", degraded_reason=reason, hits=hits, outside_digest_matches=hidden
            )

        if not self._vector_enabled:
            return keyword_report(self.vector_status)
        # Never embed vault content inside a search deadline. Catching up is
        # the job of a separate (background) reindex.
        # NOTE: docs/CLI.md "Search health and network access" documents this.
        if self.vector_issue is not None:
            return keyword_report("vector index requires reindex")

        try:
            raw = self._retrieve(query, candidate_count)
        except IndexBusyError:
            return keyword_report("index update in progress")
        except TimeoutError as exc:
            if type(exc) is not TimeoutError:
                raise
            return keyword_report("semantic search exceeded its budget")
        except memweave.SearchError as exc:
            # bge-m3 can return input-specific NaN embeddings on CUDA. Prefer
            # FTS over a CPU retry that reloads Ollama's 1.2 GB model runner.
            # https://github.com/ollama/ollama/issues/15582
            # https://github.com/ollama/ollama/issues/16625
            if "query_vec (got None)" in str(exc):
                return keyword_report("query embedding unavailable")
            if "interrupted" in str(exc):
                return keyword_report("semantic SQL exceeded its budget")
            if "chunks_vec" in str(exc):
                return keyword_report("vector index unavailable")
            raise
        hits = [Hit(path=self._abs_to_rel(r.path), score=_rescale(r.score), weight_applied=1.0) for r in raw]

        return SearchReport(
            mode="hybrid", degraded_reason=None, hits=self._with_snippets(filtered(hits), query)
        )
