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
import fcntl
import hashlib
import os
import re
import sqlite3
import urllib.error
import urllib.request
import json
from dataclasses import dataclass
from pathlib import Path

import memweave
import platformdirs
from pydantic import BaseModel

from lib.vault_index.config import VaultIndexConfig
from lib.vault_index.filters import path_passes


DEFAULT_EMBEDDING_MODEL = "ollama/bge-m3"
DEFAULT_EMBEDDING_API_BASE = "http://127.0.0.1:11434"
DEFAULT_CHUNK_TOKENS = 320
DEFAULT_CHUNK_OVERLAP = 64
PROBE_TIMEOUT_S = 1.5
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


def _ollama_probe(api_base: str, model: str) -> tuple[bool, str]:
    """Check Ollama is up and the model is pulled. Returns (ok, message).

    Strips the LiteLLM ``ollama/`` prefix from ``model`` before comparison
    against Ollama's tag list. Tags appear as e.g. ``bge-m3:latest``; we
    match on the bare name (everything before ``:``).
    """
    if not api_base.startswith("http"):
        return False, f"api_base not http(s): {api_base}"
    bare = model.split("/", 1)[1] if "/" in model else model
    bare_name = bare.split(":", 1)[0]
    url = api_base.rstrip("/") + "/api/tags"
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=PROBE_TIMEOUT_S) as resp:
            data = json.loads(resp.read())
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return False, f"Ollama unreachable at {api_base}: {exc}"
    except json.JSONDecodeError as exc:
        return False, f"Ollama returned non-JSON: {exc}"
    tags = [t.get("name", "") for t in data.get("models", [])]
    if not any(name.split(":", 1)[0] == bare_name for name in tags):
        return False, f"model '{bare_name}' not pulled (have: {tags or 'none'})"
    return True, f"ok: {bare_name} via {api_base}"


class Hit(BaseModel):
    path: str
    score: float
    weight_applied: float = 1.0


@dataclass
class SyncStats:
    indexed: int
    skipped: int
    deleted: int


class IndexBusyError(RuntimeError):
    """Raised when another process is using this vault index."""


@contextlib.contextmanager
def index_lock(cache_dir: Path, *, exclusive: bool, blocking: bool = False):
    """Hold the per-vault SQLite access lock.

    memweave uses one SQLite DB per vault cache. Reindex/sync are writers and
    must be exclusive; search is a reader and takes a shared lock so writers do
    not collide with an in-flight query. The lock is deliberately nonblocking by
    default because Hermes memory retrieval should degrade, not stall a turn.
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
            raise IndexBusyError("vault index is busy") from exc
        try:
            yield
        finally:
            fcntl.flock(lock_f.fileno(), fcntl.LOCK_UN)


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

        # Lazy auto-rebuild flag: set to True if the stored embedder fingerprint
        # differs from the current one. The next .search() or .full_reindex()
        # call will trigger a force-rebuild before serving results.
        self._needs_rebuild = self._stale_fingerprint() if self._vector_enabled else False

        # Start with an empty-extra_paths store for read-only queries.
        # full_reindex() will replace this with the full allowed-paths store.
        self._store = memweave.MemWeave(
            self._make_config(extra_paths=[])
        )

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

    def _write_fingerprint(self) -> None:
        try:
            self._fingerprint_path().write_text(self._embedder_fingerprint())
        except OSError:
            pass

    def _stale_fingerprint(self) -> bool:
        """True iff a populated index exists but was built with a different embedder.

        We only consider the fingerprint stale when there is *something* to
        invalidate — an empty cache or a never-indexed vault is a fresh install,
        not a model swap, so we don't auto-rebuild on first run.
        """
        db = self.cache_dir / "index.sqlite"
        if not db.exists():
            return False
        stored = self._read_stored_fingerprint()
        if stored is None:
            # Pre-fingerprint cache. Do not assume it is FTS-only: some live
            # deployments already have a populated vector table but predate the
            # fingerprint marker. For those, synchronous search/prefetch should
            # use the existing cache rather than spending the whole gateway
            # memory-prefetch timeout on a rebuild every turn.
            if self._vector_table_exists(db):
                return False
            return True
        return stored != self._embedder_fingerprint()

    @staticmethod
    def _vector_table_exists(db_path: Path) -> bool:
        """Return True when the cache already contains memweave's vector table."""
        try:
            with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as conn:
                row = conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='chunks_vec'"
                ).fetchone()
        except sqlite3.Error:
            return False
        return row is not None

    @staticmethod
    def _embedding_settings() -> tuple[str, str, str | None]:
        """Resolve (model, api_base, api_key) from env with bge-m3/Ollama defaults."""
        model = os.environ.get("MEMWEAVE_EMBEDDING_MODEL", DEFAULT_EMBEDDING_MODEL)
        api_base = os.environ.get(
            "MEMWEAVE_EMBEDDING_API_BASE", DEFAULT_EMBEDDING_API_BASE
        )
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
        embedding_kwargs: dict = {"model": model, "api_base": api_base}
        if api_key is not None:
            embedding_kwargs["api_key"] = api_key

        return memweave.MemoryConfig(
            workspace_dir=str(self.cache_dir),
            db_path=str(self.cache_dir / "index.sqlite"),
            progress=False,
            extra_paths=extra_paths,
            embedding=memweave.EmbeddingConfig(**embedding_kwargs),
            chunking=memweave.ChunkingConfig(
                tokens=DEFAULT_CHUNK_TOKENS, overlap=DEFAULT_CHUNK_OVERLAP
            ),
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

    def _sqlite_fts_search(self, query: str, candidate_count: int) -> list[Hit]:
        """Use the persisted FTS table directly when vector retrieval is degraded.

        memweave can still touch vector/litellm machinery during search even
        after the Ollama probe disables vectors. In sandboxed Codex sessions
        localhost access is denied, so the degraded path must avoid memweave's
        search stack entirely and query SQLite FTS directly.
        """
        db_path = self.cache_dir / "index.sqlite"
        if not db_path.exists():
            return []

        def run(match_query: str) -> list[tuple[str, float]]:
            with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as conn:
                return conn.execute(
                    """
                    SELECT path, -bm25(chunks_fts) AS score
                    FROM chunks_fts
                    WHERE chunks_fts MATCH ?
                    ORDER BY bm25(chunks_fts)
                    LIMIT ?
                    """,
                    (match_query, max(candidate_count * 3, candidate_count)),
                ).fetchall()

        try:
            rows = run(query)
        except sqlite3.OperationalError:
            safe_query = self._safe_fts_query(query)
            if not safe_query:
                return []
            try:
                rows = run(safe_query)
            except sqlite3.OperationalError:
                return []

        best_by_path: dict[str, float] = {}
        for path, score in rows:
            rel = self._abs_to_rel(path)
            best_by_path[rel] = max(best_by_path.get(rel, float("-inf")), score)
        ranked = sorted(best_by_path.items(), key=lambda item: item[1], reverse=True)
        return [
            Hit(path=path, score=round(score, 1), weight_applied=1.0)
            for path, score in ranked[:candidate_count]
        ]

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

        Writes the embedder fingerprint after a successful run so the next
        Indexer init can detect a model change and auto-rebuild.
        """
        with index_lock(self.cache_dir, exclusive=True):
            return self._full_reindex_unlocked(force=force)

    def _full_reindex_unlocked(self, force: bool = False) -> SyncStats:
        """Run memweave index assuming the caller owns the exclusive lock."""
        # Close the current store before opening a new one on the same DB.
        asyncio.run(self._store.close())

        allowed = self._allowed_vault_files()
        self._store = memweave.MemWeave(
            self._make_config(extra_paths=allowed)
        )
        result = asyncio.run(self._store.index(force=force))
        self._write_fingerprint()
        self._needs_rebuild = False
        return SyncStats(
            indexed=result.files_indexed,
            skipped=result.files_skipped,
            deleted=result.files_deleted,
        )

    def _auto_rebuild(self, reason: str) -> None:
        """Force-rebuild the index, printing a notice. Used for embedder swaps."""
        import sys
        stored = self._read_stored_fingerprint() or "none"
        current = self._embedder_fingerprint()
        print(
            f"# vault-index: rebuilding ({reason}; was {stored}, now {current})",
            file=sys.stderr,
            flush=True,
        )
        self.full_reindex(force=True)

    def sync(self) -> SyncStats:
        """Incremental re-index. Same as full_reindex without force."""
        try:
            return self.full_reindex(force=False)
        except IndexBusyError:
            return SyncStats(indexed=0, skipped=0, deleted=0)

    def search(
        self,
        query: str,
        *,
        top_k: int | None = None,
        min_score: float | None = None,
        override_digest_filter: bool = False,
        allow_rebuild: bool = True,
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

        def filtered(hits: list[Hit]) -> list[Hit]:
            cfg = self.config
            if top_k is not None:
                cfg = cfg.model_copy(update={"top_k": top_k})
            if min_score is not None:
                cfg = cfg.model_copy(update={"min_score": min_score})
            return apply_filters(
                hits,
                cfg,
                override_digest_filter=override_digest_filter,
            )

        # Auto-rebuild when the embedder fingerprint changed since the last
        # successful index. Chat prefetch calls can opt out so stale caches do
        # not spend the turn-start budget rebuilding before the model responds.
        if self._needs_rebuild and allow_rebuild:
            try:
                self._auto_rebuild(reason="embedder changed")
            except IndexBusyError:
                pass

        if not self._vector_enabled:
            return filtered(self._sqlite_fts_search(query, candidate_count))

        try:
            with index_lock(self.cache_dir, exclusive=False):
                raw = asyncio.run(
                    self._store.search(query, max_results=candidate_count, min_score=0.0)
                )
        except memweave.SearchError as exc:
            # Defensive net: reindex didn't run for some reason but the index
            # is missing chunks_vec. Trigger a rebuild and retry once.
            if "chunks_vec" in str(exc) and self._vector_enabled:
                if not allow_rebuild:
                    return filtered(self._sqlite_fts_search(query, candidate_count))
                try:
                    self._auto_rebuild(reason="chunks_vec missing")
                    with index_lock(self.cache_dir, exclusive=False):
                        raw = asyncio.run(
                            self._store.search(
                                query, max_results=candidate_count, min_score=0.0
                            )
                        )
                except IndexBusyError:
                    return []
            else:
                raise
        except IndexBusyError:
            return []
        except (sqlite3.OperationalError, memweave.StorageError) as exc:
            if "database is locked" in str(exc).lower():
                return []
            raise
        hits = [
            Hit(path=self._abs_to_rel(r.path), score=_rescale(r.score), weight_applied=1.0)
            for r in raw
        ]

        return filtered(hits)
