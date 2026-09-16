# CLI reference

Use the CLI without the Obsidian app running. Start with the
[installation instructions](index.md#installation).

## First run

Use an existing vault directory:

```bash
obsidian-knowledge setup --vault /absolute/path/to/vault --skip-claude-plugin
obsidian-knowledge doctor --query "a phrase from an existing note"
```

Setup registers and indexes an existing vault. Omit `--skip-claude-plugin` to
install the Claude plugin when `claude` is on `PATH`. Rerun setup after fixing
an error; completed steps are not rolled back. Its default deadline is
300 seconds. Increase it with `--timeout-seconds 900` for a large vault.

Commands accept `--vault` except the private `_hook` dispatcher. Without it,
they select the registered vault containing the working directory, then the
first registered vault. With no registry, they use the working directory for
backward compatibility. A malformed registry is an error, not a fallback.

## Commands

Use these commands to configure, search, and maintain the vault:

| Command | Behavior |
| --- | --- |
| `setup --vault PATH` | Register and index; optionally install the Claude plugin. |
| `init-vault-index [--vault PATH]` | Create `.claude/obsidian-knowledge.yaml` and its parent directory, or append the index template to an existing mapping. An existing `vault_index` section is left unchanged. |
| `read PATH` | Write the file's exact bytes to stdout. `PATH` must be vault-relative. |
| `write PATH [--replace]` | Read stdin, then atomically write and verify the bytes. Reject blank input, path escapes, and existing files unless you pass `--replace`. Does not reindex. |
| `reindex [--force] [--timeout-seconds N]` | Index changed files and remove stale index entries. `--force` reprocesses unchanged files too. Does not delete vault notes. |
| `search QUERY [--top-k N] [--all]` | Print ranked paths and snippets. `--all` bypasses the digest filter, not the indexing exclusions. |
| `remember TEXT [--top-k N] [--all]` | Print scored candidate homes; does not save the memory. |
| `papercut DESCRIPTION` | Append workflow friction to the repository's vault log, or the global log if no repository is identified. |
| `doctor [--query TEXT] [--top-k N] [--digest-only]` | Report index rows, semantic availability, and sample retrieval results. Repeat `--query` for multiple checks. |
| `link-hermes-memories [--hermes-memories-dir PATH]` | Compatibility helper; see [Hermes links](#legacy-hermes-links). |
| `_hook EVENT [--kind KIND] [--agent claude\|codex]` | Private JSON-on-stdin interface for host hook manifests. |

`PATH`, `QUERY`, `TEXT`, `DESCRIPTION`, `EVENT`, and `KIND` are placeholders for
command arguments. Replace `N` with a numeric value. Square brackets mark
optional arguments; omit the brackets when running a command.

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
reindex to add embeddings to keyword-indexed files.

`doctor` passes when the index is nonempty and each query returns a result.
`PASS` alone does not confirm semantic ranking or that the intended note ranked
first. Check `vector: enabled` and the printed top paths. The default sample
queries target this project's vault; use `--query` for your own notes. An empty
vault correctly fails this check.

Semantic search needs network access to the embedding endpoint, including
localhost. `EPERM` or `EACCES` indicates blocked access; check permissions before
restarting Ollama. Test the service from a terminal with network access:

```bash
curl --fail http://127.0.0.1:11434/api/tags
```

On Linux, inspect a user service with `systemctl --user status ollama` and
`journalctl --user -u ollama`; omit `--user` for a system service. A user service
normally starts at login. For startup at boot, enable lingering with
`sudo loginctl enable-linger "$USER"`. Running `ollama serve` alone does not
install or enable a service.

If an encrypted home directory holds the service unit or its required executable,
model, or credentials, don't enable lingering. The user manager can start before
Pluggable Authentication Modules mount the home directory and omit the
unavailable unit. Instead, configure the login session to start the service after
the authentication modules unlock the home directory, or
move the unit and all required runtime data outside the encrypted home directory.

For example, on a desktop that supports autostart files, create
`~/.config/autostart/ollama-after-home-unlock.desktop` with this content:

```ini
[Desktop Entry]
Type=Application
Name=Start Ollama after home unlock
Exec=/bin/sh -c "systemctl --user daemon-reload && systemctl --user start ollama.service"
NoDisplay=true
```

This entry reloads user units after login and starts only `ollama.service`.

If note reads fail with `Operation not permitted` on macOS, grant the parent
process Documents or Full Disk Access, restart it, and retry.

`search`, `remember`, and `doctor` have a 30-second deadline covering initialization
and retrieval. Override it with `OBSIDIAN_KNOWLEDGE_SEARCH_TTL_SECONDS`.
`reindex` has no deadline unless you pass `--timeout-seconds`. Always pass it
for scheduled jobs. Zero or negative deadline values disable the deadline.
A hard watchdog allows five extra seconds to terminate stuck native calls.

For model, cache, and sandbox settings, see [configuration](configuration.md).
Use `OBSIDIAN_KNOWLEDGE_VAULTS_CONFIG` to select an alternate registry YAML file.

Exit codes are 0 for success (including no search results or reindex skipped
because another process holds the lock), 2 for usage or configuration errors or a
failed `doctor` check, and 124 for a deadline. Some file or configuration write failures
return 1. Error messages identify the failing path or operation.

## Papercut logs

Record tooling problems that interrupt your workflow:

```bash
obsidian-knowledge papercut "obsidian-knowledge search stopped producing output after an automatic index rebuild; interrupted after 2 minutes"
```

Keep entries brief and self-contained: name the tool or operation, concrete
symptom or exact error, and relevant trigger. Explain task names or local labels
only if needed to understand or reproduce the problem; otherwise omit them.

With an identifiable Git `origin`, the command appends to
`wiki/repos/<owner>/<repo>/PAPERCUTS.md`. Otherwise it uses
`wiki/systems/knowledge-base/PAPERCUTS.md`. It records the working directory
and locks the log during writes.

The log directory and lock file must be writable. If access is blocked, use
the host's approved permission mechanism. If access remains unavailable, report
the failure once and continue; do not log a failed papercut with another papercut.

## Legacy Hermes links

`link-hermes-memories` links existing `MEMORY.md` and `USER.md` files from
`~/.hermes/memories` into `Utility/obsidian-knowledge/hermes/`. Both source files
must exist. Relative source directories are resolved before linking. Existing
regular destination files are preserved and reported as conflicts; only symlinks
are replaced. Configure the Obsidian linter to exclude that directory first.

This helper is not part of the current Hermes provider setup: that provider
stores durable knowledge in the wiki and disables the built-in Hermes memory
snapshots. See the [Hermes installation instructions](index.md#hermes-plugin-install).

## Verification

Run `python scripts/cli_smoke_test.py` from the checkout to exercise every
subcommand and both hook agent modes against a temporary vault. It uses the
installed CLI and configured embedding service; it does not alter your vault or
install Claude plugins. Run `obsidian-knowledge doctor` separately for your real
vault. CI also runs the full smoke test against a freshly installed wheel with
Ollama unavailable to verify keyword-only search on the first run.
