# Architecture

obsidian-knowledge gives an AI agent long-term memory backed by an Obsidian
vault: hybrid (BM25 + dense) retrieval over vault markdown, plus lifecycle hooks
that inject recalled context, protect the vault from destructive edits, and nudge
the agent to write learnings back. It ships as **two runtimes off one checkout** —
a Claude Code plugin (hooks + skills) and a Hermes Agent CLI memory provider —
over a shared retrieval library.

This is a map of *where things live and what may depend on what*, not how each
piece works (the modules document themselves). Revisit it a couple of times a
year, or when a package or invariant changes — not on every edit.

## Codemap

### `lib/vault_index/` — the shared retrieval core

The only code with real domain logic; everything else is an adapter over it.

- **`models.py`** — `Hit` (a scored `{path, score, weight_applied}` result).
  Dependency-light on purpose so `indexer` and `filters` both import it without a
  cycle (and so beartype can resolve the `Hit` forward reference at runtime).
- **`config.py`** — `VaultIndexConfig`, `IndexFilter`, `DigestFilter` (pydantic),
  and `load_config`. The vault's `.claude/obsidian-knowledge.yaml` schema.
- **`filters.py`** — `score_path`, `path_passes`, `apply_filters`. Pure functions:
  allow/deny path filtering and weight scoring.
- **`indexer.py`** — `Indexer`, the memweave (FTS5 + Ollama/dense) wrapper. Owns
  the per-vault SQLite cache, the Ollama probe/fail-soft, and `index_lock`.
- **`primer.py`** — `build_primer`, the session-start context string.
- **`cli.py`** — the `obsidian-knowledge` console entrypoint (argparse): reindex,
  search, papercut logging, doctor, hook dispatch, vault registry.
- **`papercuts.py`** — scoped, append-only, concurrency-safe workflow-friction
  logs; deliberately separate from the retrieval/indexing stack.
- **`__init__.py`** — activates **beartype** for the whole `lib` package
  (`beartype_this_package()`); runtime type checking on all of `lib.vault_index`.

### `hooks/` — the Claude Code adapter

Thin entrypoint scripts (`doctor.py`, `enforce-conventions.py`, `protect-vault.py`,
`recall-init.py`, `reflect-nudge.py`, `remind-convos.py`, `nudge-index-sync.py`,
`scan-vault-secrets.py`, `update-changelog.py`) that read a hook JSON payload on
stdin and emit a decision/message on stdout. Shared logic lives in **`hooks/hookslib/`**
(`patterns`, `vault_config`, `vault_policy`, `stop_hook`, `transcript`,
`reflect_counter`, `repo_memory`, `recall_init_lib`). `protect-vault.py`'s
`destructive_vault_ops` is the vault-write guard (decomposed per destructive-op
check: `_check_rm_mv`, `_check_find_delete`, `_check_rsync_delete`, `_check_shred`,
`_check_xargs_rm`).

### `hermes_plugin/__init__.py` — the Hermes adapter

`ObsidianKnowledgeProvider`, a Hermes `MemoryProvider`. Hermes runs Python 3.11
but `lib` needs 3.12+ (memweave), so this **bridges to the uv venv via subprocess**
rather than importing `lib` directly. Root `__init__.py` is the Hermes plugin
`register()` entrypoint.

### `scripts/`

Dev/maintenance tools: `sync_codex_plugin.py` (regenerates the Codex mirror),
`build_memory_indexes.py`, `migrate_*`, and `pre_commit_hooks/` (the custom taste
hooks — exception/print/file-length/private-test-import/future-annotations).

### `plugins/obsidian-knowledge/` — generated Codex mirror

A generated copy of the repo root for Codex's plugin marketplace, produced by
`scripts/sync_codex_plugin.py`. **Never hand-edit it**; edit the source at the repo
root and re-run the sync. Excluded from all tooling.

## Invariants (load-bearing)

- **`lib/vault_index` is the bottom layer.** It never imports from `hooks/` or
  `hermes_plugin/`. Dependency direction is `hooks → lib` and `hermes_plugin → lib`,
  never the reverse.
- **No import cycles inside `lib`.** Shared types live in `models.py`; `indexer` and
  `filters` both depend on it, not on each other's internals.
- **Hermes bridges by subprocess, not import.** `hermes_plugin` shells out to the uv
  venv (`_python_cmd()`), because of the 3.11/3.12 split. It must not `import lib`.
- **Hooks must not crash the host.** Entrypoints in `hooks/` degrade gracefully;
  broad `except` at those boundaries is deliberate and marked
  `# allow: exception-handling`.
- **`plugins/obsidian-knowledge/` is generated.** The `codex-plugin-sync` gate fails
  the build if it drifts from the source root.
- **Caches live outside the vault**, keyed per-vault (`default_cache_dir` hashes the
  vault path), so Syncthing never replicates an embeddings DB and two vaults never
  collide.

## Worktree isolation

Concurrent git worktrees (`.worktrees/<name>`) are safe to develop in:

- **Per-worktree venv** — each worktree gets its own `.venv` via `uv sync`; nothing
  is shared at a fixed path.
- **Tests self-isolate** — `tests/conftest.py` redirects `platformdirs.user_cache_dir`
  into a per-session tmp dir and disables the live Ollama probe, so parallel test
  runs never touch the real cache or network.
- **Shared global caches are content-addressed** (`~/.cache/uv`), so sharing them
  across worktrees is safe.
- The one shared mutable state is a *real* vault's on-disk index cache (keyed by
  vault path, not worktree). Point a worktree at a throwaway vault via
  `OBSIDIAN_VAULT_ROOT` / `OBSIDIAN_KNOWLEDGE_CACHE_ROOT` if you exercise real
  indexing concurrently.

See `scripts/new-worktree.sh` for the one-command ephemeral-worktree setup.
