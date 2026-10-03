# Architecture

The CLI, Streamable HTTP MCP server, and Claude Code and Codex hooks share vault retrieval and protection
components.

## Codemap

The following directories contain the shared components and host adapters:

| Location | Responsibility |
| --- | --- |
| `lib/vault_index/` | Retrieval, configuration, verified file I/O, session primer, papercut logs, and CLI orchestration. |
| `hooks/` | Lifecycle hooks, provider-owned i-insist checkers and rule template, and the dependency-light vault registry. |
| `hooks/hookslib/` | Shared protection, capture, transcript, memory-routing, and reflection logic. |
| `gardener/` | Installed vault maintenance commands, shared traversal and policy, and reviewed repairs. |
| `scripts/` | Packaging, release, and quality tools. |
| `plugins/obsidian-knowledge/` | Generated Codex distribution; edit root sources and run `scripts/sync_codex_plugin.py`. |

In the retrieval core, `config.py` defines Pydantic configuration models,
`models.py` holds shared result types, `filters.py` handles path filtering and
weights, and `indexer.py` wraps memweave's keyword and dense retrieval.
`vault_files.py` handles confined, verified writes. `mcp_server.py` exposes these
file operations and bounded CLI search subprocesses over Streamable HTTP. Importing `lib` enables
beartype runtime checks.

`vector_search.py` registers a memweave hybrid strategy using sqlite-vec's native
nearest-neighbor query. Memweave normalizes embeddings, so L2 candidate ordering
matches cosine ordering; the strategy keeps the original cosine scores and
keyword merge. Model and source filters apply before candidate selection. Pools
above sqlite-vec's 4096-candidate ceiling retain memweave's exhaustive search.

The wheel installs `hooks/vault_registry.py` as the top-level `vault_registry`
module and `hooks/hookslib/` as `hookslib`. Hooks, the CLI, and gardener commands
share these canonical module names in source checkouts and installed wheels.

## Invariants

The static import checker is `scripts/prek_hooks/check_architecture.py`.
Preserve these boundaries:

- `lib` imports neither adapters nor shared hooks, except that `primer.py`
  imports `hookslib.repo_memory` to resolve the memory destination and `cli.py`
  dispatches to `gardener.cli`.
- `hooks/hookslib` imports neither `lib`, `vault_index`, nor `gardener`.
  It may import the dependency-light `vault_registry`.
- Hook entrypoints import `hookslib` and may import `vault_index` for the doctor.
- Keep `lib` free of import cycles. Put shared result types in `models.py`.

Gardener commands reuse hook convention checks and the confined, verified vault
writer. Their shared policy excludes hidden files, dependency directories,
protected sources, sync conflicts, and symlinks. Scanners retain their documented
scope; repairs require a writable managed path and an unchanged reviewed baseline.
The skill contains guidance, while executable maintenance code ships in the wheel.

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

Use `new-feature create NAME --no-agent` from the control checkout. Repository
configuration runs `uv sync --group dev` for each managed worktree; each has its
own `.venv` and shares the uv package cache. Commit in the feature worktree, then
run `new-feature merge NAME` and `new-feature teardown NAME` from the control
checkout.

Install the Git hook with `uv run prek install` from the control checkout.
Git worktrees share hooks, so installing from a temporary worktree leaves an
interpreter path that disappears at teardown. Repository configuration marks
generated `coverage.json` as disposable, so differing coverage reports do not
block worktree transfer or teardown.

Tests use temporary caches and disable live Ollama probes. For manual indexing
in concurrent worktrees, set `OBSIDIAN_VAULT_ROOT` and
`OBSIDIAN_KNOWLEDGE_CACHE_ROOT` to a throwaway vault and cache. A real vault's
index is shared across worktrees that target it.
