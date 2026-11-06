# CLI reference

Use the CLI without the Obsidian app running. Start with the
[installation instructions](index.md#installation).

## First run

Use an existing vault directory:

```bash
obsidian-knowledge setup --vault /absolute/path/to/vault --skip-claude-plugin
obsidian-knowledge doctor --query "a phrase from an existing note"
```

Setup registers and indexes an existing vault, and installs or upgrades
i-insist, registers its global harness hooks, and writes the vault guard rules.
Add `--skip-guards` to leave existing guards unchanged. See [guard setup](hooks.md).
Omit `--skip-claude-plugin` to
install the Claude plugin when `claude` is on `PATH`. Rerun setup after fixing
an error; completed steps are not rolled back. Its default deadline is
300 seconds. Increase it with `--timeout-seconds 900` for a large vault.

Vault commands, including `garden`, accept `--vault`. After setup, no environment
variables or vault flags are needed: commands select the registered vault
containing the working directory, then the first registered vault. Commands
require an explicit or registered vault. Malformed registries and missing
selected vaults are errors.

## Commands

Use these commands to configure, search, and maintain the vault:

| Command | Behavior |
| --- | --- |
| `setup --vault PATH` | Register and index; install the Claude plugin unless skipped. Installs global guards unless `--skip-guards`. |
| `init-vault-index` | Create the shared `config.yaml` preferences and its parent directory, or append search defaults to an existing mapping. An existing `vault_index` section is left unchanged. |
| `read PATH` | Write the file's exact bytes to stdout. `PATH` must be vault-relative. |
| `write PATH [--replace]` | Read stdin, apply opt-in [configured creation defaults](configuration.md#note-creation) to new Markdown files, then atomically write and verify bytes. Reject blank input, path escapes, and existing files unless you pass `--replace`. Then [indexes the written note](#index-on-write). |
| `reindex [--force] [--path PATH] [--timeout-seconds N]` | Queue coalesced work when the worker runs (`--force` requests a new generation). Otherwise, show an in-place progress bar on interactive stderr, index changed files and remove stale index entries. Files indexed while embeddings were unavailable get vectors without rebuilding the rest. Embeddings for small notes are batched across files; see [indexing progress](#indexing-progress). `--force` reprocesses unchanged files too. `--path` (repeatable) updates only the named vault-relative files or folders: notes present are indexed, and entries at or under a path that no longer exists (or is now excluded) are removed, so passing both the old and new path records a move without re-embedding. It exits 3 when the index is not ready, the embedder is unavailable, or another index operation holds the lock. Does not delete vault notes. |
| `index-worker [--quiet-seconds N] [--scan-seconds N]` | Watch edits, coalesce work, cancel superseded indexing, and reconcile periodically. Defaults: 30 and 3600 seconds. |
| `search QUERY [--top-k N] [--all] [--json]` | Print ranked paths and snippets, or a JSON search report. `--all` bypasses the digest filter, not the indexing exclusions. |
| `remember TEXT [--top-k N] [--all]` | Print scored candidate homes; does not save the memory. |
| `papercut DESCRIPTION` | Append avoidable or fixable workflow friction to the repository's vault log, or the global log if no repository is identified. |
| `doctor [--query TEXT] [--top-k N] [--digest-only]` | Report index rows, semantic availability, and sample retrieval results. Repeat `--query` for multiple checks. |
| `garden OPERATION [--vault PATH]` | Audit vault structure and conventions, recover links, edit reviewed indexes, report questions, or repair frontmatter. See [vault maintenance](#vault-maintenance). |
| `_hook EVENT [--kind KIND] [--agent claude\|codex]` | Private JSON-on-stdin interface for host hook manifests. |

`PATH`, `QUERY`, `TEXT`, `DESCRIPTION`, `EVENT`, and `KIND` are placeholders for
command arguments. Replace `N` with a numeric value. Square brackets mark
optional arguments; omit the brackets when running a command.

`--top-k` must be positive. `read` does not load the embedding stack; `write`
does not request embeddings after a write.
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

See also [backfilling creation dates](#backfill-missing-creation-dates) for a
source-checkout script that plans repairs without inferring timestamps.

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
  ],
  "outside_digest_matches": 0
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
When keyword retrieval finds no notes in the default digest but other indexed
notes match, `outside_digest_matches` counts them (up to 50) and stderr suggests
rerunning with `--all`. This happens, for example, while a first build or
rebuild has not yet reached digest notes. It is `0` otherwise, including for
hybrid retrieval and `--all` searches.

Warnings and background reindex notices go to stderr. Failed searches exit nonzero and
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

Give the Ollama service a stable working directory. A deleted or detached
working directory can make its model runner abort with
`cannot get current path: No such file or directory`, while the HTTP server
stays alive and returns HTTP 500 from `/api/embed`. Restarting recovers the
process but does not prevent recurrence.

For a Linux user service, run `systemctl --user edit ollama` and add:

```ini
[Service]
WorkingDirectory=/
```

Then apply the override:

```bash
systemctl --user daemon-reload
systemctl --user restart ollama
systemctl --user show ollama -p WorkingDirectory
```

The last command should report `WorkingDirectory=/`. For a system service,
use `sudo systemctl` in place of `systemctl --user`. This setting requires no
username or installation path. Other process managers and manual launchers
should likewise start Ollama from a directory that remains mounted and exists
for the process lifetime; on Unix, `(cd / && exec ollama serve)` does this.
[systemd's execution documentation](https://www.freedesktop.org/software/systemd/man/latest/systemd.exec.html#WorkingDirectory=)
describes working-directory defaults and overrides.

Verify model execution, rather than only HTTP availability or model listing:

```bash
curl --fail-with-body http://127.0.0.1:11434/api/embed \
  -H 'Content-Type: application/json' \
  -d '{"model":"bge-m3","input":["embedding health check"]}'
```

Use your configured endpoint and model if they differ. A healthy response
contains a nonempty `embeddings` array. Inspect the response body and service
logs for other failures; a stable working directory does not fix every HTTP 500.

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

`search`, `remember`, and `doctor` retain a 30-second whole-command deadline,
configurable with `OBSIDIAN_KNOWLEDGE_SEARCH_TTL_SECONDS`. Semantic retrieval
gets `5 + 0.1 × top_k` seconds, using the requested result count before candidate
expansion. This linear allowance starts at semantic retrieval and shares one
absolute deadline across embedding and SQL. It is capped by remaining command
time, reserving two seconds for fallback/response (half the remaining time when
less than four seconds remain). Initialization time therefore reduces available
query time. Slow retrieval falls back to committed keyword results.
The coefficients round up observed cold-query overhead (4.7 seconds) and the
observed 10-to-50-result increase (about 0.1 seconds/result); they are
conservative allowances, not a claim that runtime scales exactly linearly. Search opens an existing database read-only and
never runs migrations, scans the vault, or launches repair work. Candidate pools
are capped at sqlite-vec's 4096 ceiling rather than reverting to exhaustive
JSON-vector retrieval for large requests. Results may contain fewer than the
requested number of hits.

Hybrid searches read the last committed SQLite snapshot while indexing proceeds;
they do not acquire the application writer lock. Keyword and vector retrieval
share one read transaction. Missing/stale vectors report `vector index requires reindex`.
Legacy `--no-rebuild` and `--no-wait` remain accepted; all searches now avoid
rebuilding and waiting. Real SQLite failures still surface as errors.

### Settled-file indexing worker

Run one supervised worker per vault/cache, alongside the MCP query service:

```bash
obsidian-knowledge index-worker --vault /absolute/path/to/vault --quiet-seconds 30 --scan-seconds 3600
```

Replace the old hourly reindex shell loop with this command. The worker uses the
already-installed `watchfiles` package and reconciles at startup and every hour.
All instances must use the same vault mount path and cache root: cache identity
includes the absolute vault path. A lifetime lock excludes a second worker.

File events and tool writes feed a durable set of dirty paths. Repeated edits
reset a per-file quiet period; unchanged scans do not. Oldest eligible files run
first. An edit during indexing cancels obsolete work and restarts that file's
cooldown while quiet files proceed. Content is checked before commit. Cancelling
HTTP cannot guarantee Ollama stops computation already in flight; completed
embedding batches remain reusable. Failed files remain pending with a 60-second
retry delay. Offline embeddings do not mark work complete. Discovery excludes
hidden directories, `_sources`, dependencies, sync conflicts, and external symlinks.

`reindex` requests received while the worker runs coalesce into pending work;
`--force` requests an unpublished replacement generation. Without a worker,
`reindex` retains synchronous maintenance behavior. MCP refresh always queues
reconciliation and requires the worker to make progress.

First builds and embedding-setting changes use a separate generation. Readers
continue using the old generation until pending work completes, then publication
atomically switches `current-generation`. Interrupted builds resume using
`building-generation.json`. Actively edited or failing files can delay this
switch; the previous index remains available. Normal file updates use short
SQLite WAL transactions. Previous generations are retained for rollback and
existing readers; remove obsolete generations only during stopped-service
maintenance. The queue and generations live outside the vault.

The worker warms Ollama with an empty `/api/embed` request at startup and every
five minutes, with a separate 120-second timeout and a 60-second retry on HTTP
failure. Embedding requests retain the model for one hour. This keeps model
loading independent of short query deadlines; no note text is embedded by the
warmup request. Other embedding providers do not receive Ollama warmups.

### Indexing progress

Indexing commits embeddings in batches sized to take about five seconds each,
starting with four chunks and adapting to the embedder's measured speed. On a
CPU-only host embedding about one chunk every two seconds, an interrupted
reindex loses at most the few chunks in flight; rerunning computes only the
remainder. Fast embedders grow to batches of 64. Indexing processes notes in
the digest (the default search scope) first, so a first build or rebuild makes
them searchable before other indexed notes.

A sync while the embedder is unavailable indexes changed files for keyword
search only. The next sync with the embedder available adds vectors to exactly
those files and keeps every other stored vector. Only a different embedding
model, endpoint, or chunking setting rebuilds vectors for the whole vault, and
cached embeddings make returning to a previous model cheap.

### Index on write

After `write` verifies new bytes, it queues the path without embedding anything.
Repeated saves coalesce. If notification fails, the write remains successful and
stderr reports the failure; periodic reconciliation discovers the content.
Search results retain the previous version until indexing succeeds. The worker
must be running for notifications to make progress.

### Reindex deadlines

`reindex` has no deadline unless you pass `--timeout-seconds`. Always pass it
for scheduled jobs. Zero or negative deadline values disable the deadline.
A hard watchdog allows five extra seconds to terminate stuck native calls and
exits with code 124. If native code blocks while holding Python's interpreter
lock, a separate helper process kills the command with SIGKILL five seconds
after that, so a stuck `reindex` cannot keep the index lock. These deadlines
cover `search`, `remember`, `doctor`, `setup`, and `reindex --timeout-seconds`.

For model, cache, and sandbox settings, see [configuration](configuration.md).
Use `OBSIDIAN_KNOWLEDGE_VAULTS_CONFIG` to select an alternate registry YAML file.

Exit codes are 0 for success (including no search results or reindex skipped
because another process holds the lock), 2 for usage or configuration errors or a
failed `doctor` check, 3 for a deferred `reindex --path`, and 124 for a deadline. Some file or configuration write failures
return 1. Error messages identify the failing path or operation.

## Papercut logs

Record friction that a future agent can avoid with a known workaround, or
that you can fix in your tools, hooks, repositories, configuration, or machine:

```bash
obsidian-knowledge papercut "obsidian-knowledge search stopped producing output after an automatic index rebuild; interrupted after 2 minutes"
```

Keep entries brief and self-contained: name the tool or operation, concrete
symptom or exact error, and relevant trigger. Explain task names or local labels
only if needed to understand or reproduce the problem; otherwise omit them.
Skip one-off transient failures, upstream bugs with no workaround, and limits
outside your control unless they recur or the workaround is non-obvious.

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
| `audit` | Report structure, index, filename, stacked-frontmatter, and convention findings. Structural checks use configured managed zones; filename checks cover visible vault files and folders; content checks cover visible vault Markdown. Findings do not change files or cause a nonzero exit. |
| `links [--format tsv\|json] [--include-stubs] [--apply]` | Read unresolved-link JSON from stdin. Filter intentional stubs and unmanaged sources; classify recoveries. Apply only unique recoveries; report ambiguous and fuzzy candidates for review. |
| `index PATH [--apply]` | Read reviewed JSON entries from stdin and render an index section. Preserve unrelated sections and prose; require a vault-relative `index.md` path. |
| `questions [--report] [--timestamp ISO_TIME] [--apply]` | Scan managed Markdown for question callouts. Default output is TSV; `--report` previews the standard Markdown report. `--apply` writes `Utility/obsidian-knowledge/reports/open-questions.md`. |
| `frontmatter PATH... [--apply]` | Preview removal of stray stacked frontmatter markers. Real second YAML blocks require a manual merge and return nonzero. Paths must be vault-relative Markdown files. |

Filename checks reuse `illegal_filename_chars` from shared preferences, also
used by the write-time guard. `ILLEGAL_FILENAME` findings include the
vault-relative path and offending characters. They cover attachments and folder
names as well as notes, and are disabled when the character list is absent or
empty. They retain the maintenance exclusions below. The audit never renames
paths; use Obsidian's rename/move commands to preserve internal links.

Index coverage checks recognize existing vault-root targets first, then paths
relative to the source folder and its ancestors, nearest first. A nearer
existing target prevents credit for a different child. This handles common
shortened folder paths without guessing from arbitrary suffixes or aliases.
Heading and block suffixes start at `#`; a literal caret in a filename is not
treated as a block separator. This filesystem check does not certify every
Obsidian link-resolution or filename rule.

Repairs default to previews. Use `--apply` for deterministic repairs; preview
when review would help. Ambiguous link targets and real frontmatter merges
require judgment.
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

## Backfill missing creation dates

From the source checkout, `scripts/backfill_created.py` produces a reviewed JSON
plan before any note changes. It does not infer dates from filesystem creation
or modification times, filenames, or Git commits. Identify metadata properties
that actually recorded creation, or supply independently verified evidence:

```bash
uv run python scripts/backfill_created.py plan \
  --vault /absolute/path/to/vault \
  --plan /tmp/created-review.json \
  --source-field created_at
```

Omit `--source-field` when no trustworthy alias exists. `--source-field` is
repeatable; conflicting values are unresolved. Use `--path` to narrow the scan
to a vault-relative file or folder. With no trusted evidence, a missing date is
reported as unresolved and left alone. Existing `created` properties, including
explicit nulls and empty values, are preserved.

Pass `--syncthing-history /absolute/path/to/.stversions` to discover explicit
`created` properties in archived notes. The script maps Syncthing version
filenames back to their original relative paths; it never uses the archive
filename's timestamp as a creation date. Conflicting historical values remain
unresolved. If the archived and current bodies differ, the proposal has
`requires_review: true` and application skips it. Matching bodies ignore
frontmatter and leading blank lines only. External vetted evidence for the
same date can confirm a historical proposal.

For dates recovered from verified backups or other records, pass `--evidence`
with a JSON file in this format:

```json
{
  "records": [
    {
      "path": "wiki/example.md",
      "created": "2024-06-01T10:30:00-07:00",
      "source": "Verified original creation metadata from backup manifest"
    }
  ]
}
```

The evidence file is an explicitly trusted input; the script validates its
dates, not the truth of its source descriptions. Modification or event dates
are not creation evidence. Future or invalid dates are rejected. Preserve the
original precision and timezone: a known calendar date can be `2024-06-01`,
without inventing a time or offset.

Evidence records may include `requires_review: true` to retain an unconfirmed
lead without applying it. Optional `note_sha256` binds evidence to the current
note bytes; a mismatch is unresolved. Successful create-only tool records can
establish a creation day; an edit, backup observation, or research event alone
cannot. Historical path reuse and renamed notes require particular care.

The plan records each proposal's path, date, source, and original SHA-256, plus
unresolved paths and reasons. Store it outside the vault; it is created with
mode `0600` and an existing plan is never overwritten. Planning is the default
action and does not change notes. Review the plan before running:

```bash
uv run python scripts/backfill_created.py apply \
  --vault /absolute/path/to/vault \
  --plan /tmp/created-review.json
```

Both actions respect configured managed/assisted zones, read-only paths,
creation-template exclusions, protected sources, hidden paths, sync conflicts,
symlinks, and existing published notes. Application rechecks the current policy
and all reviewed baselines before starting. It adds only missing `created`
properties, preserving existing YAML comments, body bytes, line endings, BOM,
permissions, and `updated`/`modified` metadata. File modification time naturally
changes when the file is written.

Each write is atomic and checks the original bytes again immediately before
replacement. The batch is not a filesystem transaction: a concurrent edit can
stop it partway. Rerunning the plan preserves notes that already have `created`.
Retain the plan as the provenance record for the repair.
The application result lists skipped `pending_review` paths separately.

### Accept filename dates and infer additional dates

When approximate dates are acceptable, the separate inference command produces
evidence from a previous plan without changing notes:

```bash
uv run python -m scripts.infer_created \
  --input-plan /tmp/created-review.json \
  --output-evidence /tmp/created-inferred-evidence.json \
  --filename-dates \
  --history /absolute/path/to/vault/.stversions \
  --mtime

uv run python scripts/backfill_created.py plan \
  --vault /absolute/path/to/vault \
  --evidence /tmp/created-inferred-evidence.json \
  --plan /tmp/created-inferred-review.json
```

`--filename-dates` explicitly accepts a valid, nonfuture leading `YYYY-MM-DD`
as authoritative for missing creation dates, ahead of other evidence. This is
opt-in because filenames can otherwise describe a document or event date.
Existing `created` values remain unchanged. Neither command guesses incomplete
dates such as `2024-06`.

For undated filenames, existing verified proposals remain intact. Historical
proposals that previously required review become estimates. Other missing
dates prefer archived `created` metadata; conflicting historical dates use the
earliest value and identify the conflict in the source. Repeat `--dated-path`
for scopes where filename or opening dates describe note-writing and should
be used as estimates. Unlike `--filename-dates`, those dates must not postdate
an available observation.

`--mtime` enables an upper-bound fallback: the earliest valid current/archived
file modification time or `updated`/`modified` property. Optional
`--observations` accepts JSON `records` containing `path`, `observed` (an ISO
date or timestamp), and `source`, for example a backup's first observation or
preserved modification date. These are estimates, not proof of creation.
Filesystem ctime and the timestamps in Syncthing version filenames are never
used. Inferred dates use calendar-day precision in the executing host's local
timezone for filesystem timestamps.

The resulting records and review plan mark approximations with `estimated:
true` and retain their basis in `source`. Accepted filename dates have
`estimated: false`. Evidence binds to each note's SHA-256, and output files are
private, outside the vault, and never overwritten. Applying the reviewed plan
also applies its estimates; review their sources before application. Only the
`created` property is added, so retain the plan to distinguish estimates later.

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
