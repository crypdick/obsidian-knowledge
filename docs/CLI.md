# CLI reference

Use the CLI without the Obsidian app running. Start with the
[installation instructions](index.md#installation).

## First run

Use an existing vault directory:

```bash
obsidian-knowledge setup --vault /absolute/path/to/vault --skip-claude-plugin
obsidian-knowledge doctor --query "a phrase from an existing note"
```

Setup registers and indexes an existing vault. Add `--install-guards` to install
or upgrade i-insist and register global harness hooks and vault guard rules.
Without this flag, setup leaves existing guards unchanged. See [guard setup](hooks.md).
Omit `--skip-claude-plugin` to
install the Claude plugin when `claude` is on `PATH`. Rerun setup after fixing
an error; completed steps are not rolled back. Its default deadline is
300 seconds. Increase it with `--timeout-seconds 900` for a large vault.

Vault commands, including `garden`, accept `--vault`. After setup, no environment
variables or vault flags are needed: commands select the registered vault
containing the working directory, then the first registered vault. With no
registry, they use the working directory for backward compatibility. A malformed
registry or missing selected vault is an error, not a fallback.

## Commands

Use these commands to configure, search, and maintain the vault:

| Command | Behavior |
| --- | --- |
| `setup --vault PATH` | Register and index; install the Claude plugin unless skipped. Global guards require `--install-guards`. |
| `init-vault-index [--vault PATH]` | Create `.claude/obsidian-knowledge.yaml` and its parent directory, or append the index template to an existing mapping. An existing `vault_index` section is left unchanged. |
| `read PATH` | Write the file's exact bytes to stdout. `PATH` must be vault-relative. |
| `write PATH [--replace]` | Read stdin, then atomically write and verify the bytes. Reject blank input, path escapes, and existing files unless you pass `--replace`. Does not reindex. |
| `reindex [--force] [--timeout-seconds N]` | Index changed files and remove stale index entries. `--force` reprocesses unchanged files too. Does not delete vault notes. |
| `search QUERY [--top-k N] [--all] [--json]` | Print ranked paths and snippets, or a JSON search report. `--all` bypasses the digest filter, not the indexing exclusions. |
| `remember TEXT [--top-k N] [--all]` | Print scored candidate homes; does not save the memory. |
| `papercut DESCRIPTION` | Append workflow friction to the repository's vault log, or the global log if no repository is identified. |
| `doctor [--query TEXT] [--top-k N] [--digest-only]` | Report index rows, semantic availability, and sample retrieval results. Repeat `--query` for multiple checks. |
| `garden OPERATION [--vault PATH]` | Audit vault structure and conventions, recover links, edit reviewed indexes, report questions, or repair frontmatter. See [vault maintenance](#vault-maintenance). |
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

## JSON search output

Use `--json` for scripts and agents:

```bash
obsidian-knowledge search "orchid greenhouse" --json --top-k 5
```

Successful searches write one JSON object to stdout:

```json
{
  "mode": "keyword",
  "degraded_reason": "query embedding unavailable",
  "hits": [
    {
      "path": "wiki/orchid.md",
      "score": 42.1,
      "weight_applied": 1.5,
      "snippet": "Purple orchids grow in the greenhouse."
    }
  ]
}
```

`mode` reports the retrieval used for this query: `hybrid` combines keyword and
vector retrieval; `keyword` uses only the keyword index. `degraded_reason` is
`null` for hybrid retrieval. For keyword retrieval, it describes the unavailable
embedding service, query embedding, or vector index. An explicitly disabled
vector provider reports `disabled-by-caller`. Reason text is diagnostic;
branch on `mode`, not its wording.

Hits use the same filters, weights, snippets, and ordering as text output.
`score` is a ranking value, not a confidence percentage; scores from different
retrieval modes are not directly comparable. A successful search with no matches
returns `"hits": []` and still includes the retrieval mode and reason.

Warnings and rebuild progress go to stderr. Failed searches exit nonzero and
do not emit a success object. Timeout and busy exit codes are described below.

## Search health and network access

The default embedding service is Ollama at `http://127.0.0.1:11434`, using
`bge-m3`. If it is unavailable or the model is absent, indexing and search fall
back to keyword retrieval. Install the model with `ollama pull bge-m3`, then
reindex to add embeddings to keyword-indexed files.

Models with the `ollama/` prefix use Ollama’s batch `/api/embed` endpoint directly,
without importing LiteLLM. Other model identifiers retain memweave’s LiteLLM
provider. LiteLLM remains installed because memweave requires it.

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
Vector searches wait for an active index writer within that deadline, including
when search needs to rebuild the index. Keyword search can read committed
SQLite data while indexing continues. If lock waiting exhausts the deadline,
the command reports a timeout and exits with code 124. Database contention that
persists after SQLite's own wait reports a busy error with code 2; it does not
appear as an empty result set.
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

## Vault maintenance

Gardener commands ship with the installed CLI. They do not require executable
scripts from a plugin cache. Use `obsidian-knowledge garden --help` to list
operations, or `obsidian-knowledge garden OPERATION --help` for their arguments.

| Operation | Behavior |
| --- | --- |
| `audit` | Report structure, index, stacked-frontmatter, and convention findings. Structural checks use configured managed zones; content checks cover visible vault Markdown. Findings do not change files or cause a nonzero exit. |
| `links [--format tsv\|json] [--include-stubs] [--apply]` | Read unresolved-link JSON from stdin. Filter intentional stubs and unmanaged sources; classify recoveries. Apply only unique recoveries; report ambiguous and fuzzy candidates for review. |
| `index PATH [--apply]` | Read reviewed JSON entries from stdin and render an index section. Preserve unrelated sections and prose; require a vault-relative `index.md` path. |
| `questions [--report] [--timestamp ISO_TIME] [--apply]` | Scan managed Markdown for question callouts. Default output is TSV; `--report` previews the standard Markdown report. `--apply` writes `Utility/obsidian-knowledge/reports/open-questions.md`. |
| `frontmatter PATH... [--apply]` | Preview removal of stray stacked frontmatter markers. Real second YAML blocks require a manual merge and return nonzero. Paths must be vault-relative Markdown files. |

Repairs default to previews. Add `--apply` after reviewing the output.
Maintenance excludes hidden files, dependency directories, protected sources,
Syncthing conflicts, and symlinks. Writes require a managed path, respect
configured read-only paths, reject changed baselines, and use the verified
atomic writer. The standard question report is an allowed derivative state path.
Repairs refuse existing published notes (`dg-publish: true`); use the manual
edit and consent workflow described in [vault protection](hooks.md#vault-protection).
Malformed frontmatter also requires manual repair before applying changes.

```bash
obsidian-knowledge garden audit
obsidian-knowledge garden frontmatter wiki/example.md
obsidian-knowledge garden questions --report
```

Link recovery still needs the Obsidian CLI to supply unresolved links:

```bash
obsidian vault="My Vault" unresolved verbose format=json | obsidian-knowledge garden links
```

Use Obsidian's move and rename commands for structural changes so it updates
internal links. The vault-organizer skill describes triage and index review.

## Verification

Run `python scripts/cli_smoke_test.py` from the checkout to exercise every
subcommand and both hook agent modes against a temporary vault. It uses the
installed CLI and configured embedding service; it does not alter your vault or
install Claude plugins. Run `obsidian-knowledge doctor` separately for your real
vault. CI also runs the full smoke test against a freshly installed wheel with
Ollama unavailable to verify keyword-only search on the first run.
