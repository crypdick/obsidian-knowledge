# CLI reference and troubleshooting

The standalone CLI operates on files; it does not require the Obsidian app to be
running. Install with `uv tool install obsidian-knowledge`. For this repository's
local development install, follow [AGENTS.md](../AGENTS.md).

## First run

Use an existing vault directory:

```bash
obsidian-knowledge setup --vault /absolute/path/to/vault --skip-claude-plugin
obsidian-knowledge doctor --query "a phrase from an existing note"
```

`setup` validates the vault and its configuration, registers the vault in
`~/.config/obsidian-knowledge/vaults.yaml`, and indexes its files. It preserves
other registry keys and rejects malformed registries without overwriting them.
Omit `--skip-claude-plugin` to also install the Claude plugin when `claude` is on
PATH. A failed Claude install returns a nonzero exit code; rerun after fixing it,
or use `--skip-claude-plugin` for CLI-only, Codex, or Hermes setup. Registration
may already have completed when a later step fails, and rerunning is safe.

Setup has a 300-second deadline. Increase it with `--timeout-seconds 900` for a
large first index. A timeout does not undo completed registration or indexing.

Commands accept `--vault` except the private `_hook` dispatcher. Without it,
they select the registered vault containing the working directory, then the
first registered vault. With no registry, they use the working directory for
backward compatibility. A malformed registry is an error, not a fallback.

## Commands

| Command | Behavior |
| --- | --- |
| `setup --vault PATH` | Register and index; optionally install the Claude plugin. |
| `init-vault-index [--vault PATH]` | Create `.claude/obsidian-knowledge.yaml` and its parent directory, or append the index template to an existing mapping. An existing `vault_index` section is left unchanged. |
| `read PATH` | Write the file's exact bytes to stdout. PATH must be vault-relative. |
| `write PATH [--replace]` | Read stdin, atomically write and verify the bytes. Reject blank input, path escapes, and existing files unless `--replace` is given. Does not reindex. |
| `reindex [--force] [--timeout-seconds N]` | Index changed files and remove stale index entries. `--force` reprocesses unchanged files too. Does not delete vault notes. |
| `search QUERY [--top-k N] [--all]` | Print ranked paths and snippets. `--all` bypasses the digest filter, not the indexing exclusions. |
| `remember TEXT [--top-k N] [--all]` | Print scored candidate homes; does not save the memory. |
| `papercut DESCRIPTION` | Append workflow friction to the repository's vault log, or the global log if no repository is identified. |
| `doctor [--query TEXT] [--top-k N] [--digest-only]` | Report index rows, semantic availability, and sample retrieval results. Repeat `--query` for multiple checks. |
| `link-hermes-memories [--hermes-memories-dir PATH]` | Legacy compatibility helper; see below. |
| `_hook EVENT [--kind KIND] [--agent claude\|codex]` | Private JSON-on-stdin interface for host hook manifests. |

`--top-k` must be positive. `read` and `write` do not load the embedding stack.
For literal Markdown containing backticks, dollar signs, or wikilinks, use a
quoted heredoc delimiter:

```bash
obsidian-knowledge write wiki/example.md <<'NOTE'
# Example

Literal `code`, $variables, and [[wikilinks]].
NOTE
obsidian-knowledge read wiki/example.md
obsidian-knowledge reindex --timeout-seconds 300
```

## Search health and network access

The default embedding service is Ollama at `http://127.0.0.1:11434`, using
`bge-m3`. If it is unavailable or the model is absent, indexing and search fall
back to keyword retrieval. Install the model with `ollama pull bge-m3`, then
reindex; unchanged keyword-indexed files will receive embeddings.

`doctor` passes when the index is nonempty and each query returns a result.
**PASS alone does not establish semantic search is working or that the intended
note ranked first.** Check `vector: enabled` and the printed top paths. Its
default sample queries target this project's vault; use `--query` for your own
notes. An empty vault correctly fails this check.

Local retrieval uses LiteLLM's bundled pricing metadata by default, so it does
not need access to `raw.githubusercontent.com`. SOCKS proxy support is included
in the install. Setting `LITELLM_LOCAL_MODEL_COST_MAP=False` explicitly opts into
LiteLLM's remote metadata behavior and requires the corresponding network access.
The embedding endpoint itself still needs network permission, including when it
is localhost. EPERM/EACCES indicates blocked access, not a stopped Ollama server.

Search, remember, and doctor have a 30-second deadline covering initialization
and retrieval. Override it with `OBSIDIAN_KNOWLEDGE_SEARCH_TTL_SECONDS`.
Reindex has no deadline unless `--timeout-seconds` is supplied; always supply one
for scheduled jobs. Zero or negative deadline values disable the deadline.
A hard watchdog allows five extra seconds to terminate stuck native calls.

Useful overrides:

| Environment variable | Purpose |
| --- | --- |
| `OBSIDIAN_KNOWLEDGE_VAULTS_CONFIG` | Alternate registry YAML path. |
| `OBSIDIAN_KNOWLEDGE_CACHE_ROOT` | Alternate cache base; the index uses an `obsidian-knowledge/<vault-key>` subdirectory. |
| `MEMWEAVE_EMBEDDING_MODEL` | Embedding model, default `ollama/bge-m3`. |
| `MEMWEAVE_EMBEDDING_API_BASE` | Embedding endpoint. |
| `MEMWEAVE_EMBEDDING_API_KEY` | Optional embedding authentication. |

Exit codes are 0 for success (including no search results or reindex skipped
because another process holds the lock), 2 for usage/configuration errors or a
failed doctor, and 124 for a deadline. Some file/configuration write failures
return 1. Error messages identify the failing path or operation.

## Legacy Hermes links

`link-hermes-memories` links existing `MEMORY.md` and `USER.md` files from
`~/.hermes/memories` into `Utility/obsidian-knowledge/hermes/`. Both source files
must exist. Relative source directories are resolved before linking. Existing
regular destination files are preserved and reported as conflicts; only symlinks
are replaced. Configure the Obsidian linter to exclude that directory first.

This helper is not part of the current Hermes provider setup: that provider
stores durable knowledge in the wiki and disables Hermes's built-in memory
snapshots. See the [Hermes installation instructions](../README.md#hermes-plugin-install).

## Verification

Run `python scripts/cli_smoke_test.py` from the checkout to exercise every
subcommand and both hook agent modes against a temporary vault. It uses the
installed CLI and configured embedding service; it does not alter your vault or
install Claude plugins. Run `obsidian-knowledge doctor` separately for your real
vault. CI also runs the full smoke test against a freshly installed wheel with
Ollama unavailable, ensuring keyword-only first-run behavior works.
