# Architecture

The CLI plus Claude Code and Codex hooks share vault retrieval and protection
components.

## Codemap

The following directories contain the shared components and host adapters:

| Location | Responsibility |
| --- | --- |
| `lib/vault_index/` | Retrieval, configuration, verified file I/O, session primer, papercut logs, and CLI orchestration. |
| `hooks/` | Lifecycle hooks, provider-owned i-insist checkers and rule template, and the dependency-light vault registry. |
| `hooks/hookslib/` | Shared protection, capture, transcript, memory-routing, and reflection logic. |
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
- `hooks/hookslib` imports neither `lib` nor `vault_index`.
  It may import the dependency-light `vault_registry`.
- Hook entrypoints import `hookslib` and may import `vault_index` for the doctor.
- Keep `lib` free of import cycles. Put shared result types in `models.py`.

Review dynamic imports and generated subprocess code separately; the checker
covers static imports, including local and relative imports.

Runtime requirements:

- i-insist normalizes tool inputs. Vault checks consume neutral file changes and
  shell commands directly; the provider owns no harness or approval adapter.
- Hooks must not crash the host. Broad catches at entrypoint boundaries are
  deliberate and marked `# allow: exception-handling`.
- Keep the Codex distribution generated. The `codex-plugin-sync` check detects drift.
- Store caches outside the vault, keyed by vault path, to avoid sync conflicts
  and collisions between vaults.

## Worktree isolation

Use `scripts/new-worktree.sh` to create a development worktree. Each worktree
has its own `.venv`. Worktrees can share the uv package cache.

Tests use temporary caches and disable live Ollama probes. For manual indexing
in concurrent worktrees, set `OBSIDIAN_VAULT_ROOT` and
`OBSIDIAN_KNOWLEDGE_CACHE_ROOT` to a throwaway vault and cache. A real vault's
index is shared across worktrees that target it.
