# Architecture

The CLI, Claude Code and Codex hooks, and Hermes memory provider share vault
retrieval and protection components.

## Codemap

| Location | Responsibility |
| --- | --- |
| `lib/vault_index/` | Retrieval, configuration, verified file I/O, session primer, papercut logs, and CLI orchestration. |
| `hooks/` | Claude Code hook entrypoints and the dependency-light vault registry. |
| `hooks/hookslib/` | Shared protection, capture, transcript, memory-routing, and reflection logic. |
| `hermes_plugin/` | Hermes memory provider and lifecycle adapter. The root `__init__.py` registers it. |
| `scripts/` | Development, migration, packaging, and quality tools. |
| `plugins/obsidian-knowledge/` | Generated Codex distribution; edit root sources and run `scripts/sync_codex_plugin.py`. |

In the retrieval core, `config.py` defines Pydantic configuration models,
`models.py` holds shared result types, `filters.py` handles path filtering and
weights, and `indexer.py` wraps memweave's keyword and dense retrieval.
`vault_files.py` handles confined, verified writes. Importing `lib` enables
beartype runtime checks.

The wheel installs `hooks/vault_registry.py` as the top-level `vault_registry`
module so hooks and the CLI share one registry implementation.

## Invariants

The static import checker is `scripts/prek_hooks/check_architecture.py`.
Preserve these boundaries:

- `lib` imports neither adapters nor shared hooks, except that `primer.py`
  imports `hookslib.repo_memory` to resolve the memory destination.
- `hooks/hookslib` imports neither `lib`, `vault_index`, nor `hermes_plugin`.
  It may import the dependency-light `vault_registry`.
- Hook entrypoints import `hookslib` and may import `vault_index` for the doctor.
- `hermes_plugin` may import `hookslib` for reflection counters. It calls the
  retrieval environment through subprocesses and never imports `lib` or
  `vault_index` into the host process. This accommodates Hermes's Python 3.11
  runtime and the retrieval stack's Python 3.12+ requirement.
- Keep `lib` free of import cycles. Put shared result types in `models.py`.

Review dynamic imports and generated subprocess code separately; the checker
covers static imports, including local and relative imports.

Runtime requirements:

- Protection checks receive the workdir and normalize paths without changing cwd.
- Only the indexer reports sync completion. On `IndexBusyError`, Hermes retains
  dirty state and retries on a later turn.
- Hooks must not crash the host. Broad catches at entrypoint boundaries are
  deliberate and marked `# allow: exception-handling`.
- Keep the Codex distribution generated. The `codex-plugin-sync` check detects drift.
- Store caches outside the vault, keyed by vault path, to avoid sync conflicts
  and collisions between vaults.

## Worktree isolation

Use `scripts/new-worktree.sh` to create a development worktree. Each worktree
has its own `.venv`; uv's package cache can be shared.

Tests use temporary caches and disable live Ollama probes. For manual indexing
in concurrent worktrees, set `OBSIDIAN_VAULT_ROOT` and
`OBSIDIAN_KNOWLEDGE_CACHE_ROOT` to a throwaway vault and cache. A real vault's
index is shared across worktrees that target it.
