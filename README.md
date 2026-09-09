# Obsidian Knowledge

A plugin marketplace and CLI for maintaining Obsidian knowledge base vaults
with Claude Code, Codex, and Hermes.

[Documentation](https://crypdick.github.io/obsidian-knowledge/) ·
[Preview and contribute to the docs](docs/contributing-docs.md)

## Skills

### vault-organizer

Maintains vault organization through a single-pass pipeline:

- **Sync indexes** — creates and updates `index.md` files with thin pointer entries for managed zones
- **Organize files** — moves misplaced files to appropriate locations using the Obsidian CLI
- **Rename ambiguous files** — detects files with non-descriptive names
  (device-generated, hash-based, generic labels), reads their content, and
  renames them following the vault's naming conventions from CLAUDE.md
- **Fix broken links** — detects unresolved links and resolves them when
  possible, flags ambiguous cases for human review
- **Report issues** — maintains a `needs-attention.md` worklist for issues
  requiring human judgment
- **Regenerate reports** — rewrites `reports/open-questions.md` from
  `> [!question]` callouts across `wiki/`, giving agents and humans a
  single place to see unresolved questions flagged in prose

### remember-conversations

Selectively files durable, novel conversation outputs as permanent vault
notes, so insights compound without turning routine activity into prompt
overhead:

- **Canonical notes** — learning pages for reusable concepts, diary notes for
  reusable incident/process accounts, and convo notes for analytical synthesis
- **Changelog updates** — after an actual durable vault mutation, creates or
  reuses one terse same-session file in `changelog/`
- **Automatic placement** — learning pages use the canonical topic location;
  analytical and narrative notes use `convos/` and `diary/` subfolders
- **Stop hook integration** — one reminder asks the agent to search first and
  file at most one canonical note only when a durable delta qualifies

## Hooks

### Vault protection (PreToolUse)

`protect-vault.py` runs before every Bash, Write, and Edit tool call.
It provides four layers of safety:

**Read-only `_sources/` directories.** Folders named `_sources/` anywhere
in the vault tree are protected from agent writes. These typically hold
irreplaceable originals (tax records, legal filings, vital docs, property
deeds). Agents can read them to generate summaries and indexes, but cannot
create, modify, rename, move, or delete files inside them.

**Destructive command guards.** Recursive `rm` and `mv` targeting paths
that appear to be inside an Obsidian vault are blocked.

**Published file guard.** Write and Edit to any vault file with
`dg-publish: true` in its frontmatter are blocked — edits to published
files go live on the website and require explicit user confirmation.

**Auto-memory redirect.** Agents are blocked from writing operational
knowledge (`feedback_*.md`, `project_*.md`, `reference_*.md`) to their
per-project auto-memory. Auto-memory is a silo invisible to other sessions,
other tools, and vault search. The hook redirects this knowledge to a
standardized vault location, scoped to the agent's current context:

- Inside a git repo → `<vault>/wiki/repos/<owner>/<repo>/memory/` (parsed
  from `git remote get-url origin`; portable across hosts).
- Outside any repo → `<vault>/wiki/systems/machines/<hostname>/memory/`
  (host-scoped fallback).

Each memory dir mirrors Claude's native layout (`MEMORY.md` index plus
one `feedback_*.md` / `project_*.md` / `reference_*.md` per fact), so
the workflow is identical — only the storage location changes. The
SessionStart primer surfaces the resolved path so agents know where
to read and write at session start. Migrate existing per-project
memories with `scripts/migrate_claude_memory.py`.

**Escape hatch.** Prefix a Bash command with `I_AM_BEING_CAREFUL=1` to
bypass the `_sources/` and published-file guards after the user explicitly
confirms. The auto-memory redirect has no escape hatch — write to the wiki
instead.

### For agents: add this line to the user's primary `CLAUDE.md`

Built-in Claude auto-memory under `~/.claude/projects/*/memory/` is
replaced by the `obsidian-knowledge` plugin. Agents should add a single
pointer to the user's primary memory file (`~/.claude/CLAUDE.md`) so
sessions on hosts without this plugin still know where to look:

```markdown
Agent memory is managed by the obsidian-knowledge plugin; refer to it
for memory location, read/write conventions, and session-start recall.
```

### Stop hooks

Capture hooks support Claude and Codex transcripts and emit at most once per human
turn. Hook prompts, goal continuations, and injected environment instructions do not
rearm capture; elapsed time alone never does. Without a readable transcript, capture
emits at most once per session; without session identity it stays silent. Capture can
run outside the vault when exactly one vault is configured. Other maintenance hooks
retain their own vault and cooldown gates.

The capture reminder also asks agents to repair verified stale instructions already
encountered, under the instruction-repair rules in the obsidian-knowledge skill. It
does not request a new audit or authorize policy changes.

- **capture-session.py** — makes one selective capture decision. The default is
  to file nothing; qualifying information must be durable, novel, reusable,
  searched for first, and not cheaply recoverable from another source
- **scan-vault-secrets.py** — runs `detect-secrets` against the vault
  and surfaces unaudited findings to the agent. The plugin makes no
  assumptions about which password manager you use — agents are told
  to follow your vault's documented secrets-management convention, so
  **document yours somewhere agents can find it** (root `CLAUDE.md` or
  a wiki note). The first scan walks the entire vault (slow, ~1 min
  on a few thousand files); subsequent scans are incremental against
  the baseline at `<vault>/.secrets.baseline`.

  Marks false positives two ways:
  - **Inline sentinel** (recommended for prose notes) — append on the
    same line:
    ```
    token = "fake"  <!-- pragma: allowlist secret -->     # markdown / xml
    token = "fake"  # pragma: allowlist secret             # yaml / sh / py
    token = "fake"  // pragma: allowlist secret            # js / go / c
    ```
  - **Baseline audit** (batch-mark existing findings):
    ```
    detect-secrets audit <vault>/.secrets.baseline
    ```

  The hook uses the `detect-secrets` Python API directly with a filter
  set tuned for prose: it drops the `is_likely_id_string` and
  `is_indirect_reference` filters that the `detect-secrets scan` CLI
  applies, because those silently swallow the `token = "..."` pattern
  exactly as it appears in markdown notes. Lower-entropy passphrases
  that elude detect-secrets entirely (dictionary-word passwords in
  narrative prose) can be added one-per-line to
  `<vault>/.secrets.known-leaked` for verbatim string-match alerting.

  Requires [`uv`](https://docs.astral.sh/uv/) on `PATH` (the hook is a
  uv inline script — `detect-secrets` is installed automatically into a
  uv-managed cache, no global pip install needed).

### recall-init (SessionStart)

`recall-init.py` runs at every session start. Injects the harness
primer: a compact context block covering memory location, recall
via `obsidian-knowledge search`, capture at session end, and friction
reflection. The primer stands alone — agents that read only this know how
to operate within the harness.

### reflect-nudge (PostToolUse on Bash)

`reflect-nudge.py` fires every 100 bash invocations within a session.
Continuous — no per-session suppression. Reminds the agent to fix and verify
in-scope defects and log unrelated harness or tooling friction as a papercut.

## Commands

### obsidian-knowledge papercut "<description>"

Appends the friction to `wiki/repos/<owner>/<repo>/PAPERCUTS.md` when the current
directory belongs to a Git repository with an identifiable `origin`. Outside such
a repository, it falls back to `wiki/systems/knowledge-base/PAPERCUTS.md`. The
log is lock-protected for concurrent agents. It records friction only—it does not
diagnose the issue or modify the harness.

Bugs introduced by the agent, failed validation of its changes, and defects required
to complete the request must be fixed and verified within the active task. Logging
never defers that work. Reserve papercuts for unrelated harness or tooling friction;
routine debugging does not need entries.

The vault log's directory and lock file must be writable. In a sandbox where the
vault is outside the writable roots, use the host's approved permission mechanism.
Permission and read-only-filesystem failures exit with status 1 and explain the
required access. If permission is unavailable, report the failure once and
continue the task; do not recursively log the failed logging attempt.

Reports created by v3.22.24 remain untouched under
`wiki/systems/knowledge-base/papercuts/`; they are not automatically assigned to a
repository because their original scope may be ambiguous.

### obsidian-knowledge search "<query>"

Searches the indexed `wiki/` tree and returns ranked `score  path` lines.
Pass `--all` to include normally-hidden zones (`Inbox/`, `Journal/`).

Semantic ranking needs network access to Ollama, even at `127.0.0.1`. A connection
denied with `EPERM` or `EACCES` indicates sandbox or OS restrictions, not evidence
that the server is stopped. Retry through the host's approved permission mechanism
or use degraded keyword ranking. Check the service outside the restricted process
before starting another server. A Linux systemd user service starts at login unless
lingering is enabled; inspect it with `systemctl --user status ollama` and
`journalctl --user -u ollama` (system services omit `--user`).

### Hermes plugin install

Install the repo with Hermes's native plugin manager:

```bash
hermes plugins install crypdick/obsidian-knowledge --enable
hermes config set memory.provider obsidian-knowledge
hermes config set memory.memory_enabled false
hermes config set memory.user_profile_enabled false
```

The installed checkout is both a general Hermes plugin (vault-protection and
reminder hooks) and a memory provider (`obsidian-knowledge`) for primer, prefetch,
`vault_search`, and a provider-owned `memory()` redirect error. The built-in
Hermes `MEMORY.md` / `USER.md` prompt snapshots should be disabled when this
provider is active; durable Hermes profile facts live in the vault at
`wiki/systems/knowledge-base/index.md`, which is injected with a hard size cap
and should stay a thin wikilink index to detailed notes. Use
`hermes plugins update obsidian-knowledge` after pushing repo updates.

### obsidian-knowledge remember "<memory>"

Deterministic placement helper for durable facts. It does not write files or
invoke an agent. It searches the vault and prints scored candidate homes so a
human or agent can choose where to store the memory.

See the [CLI reference](docs/CLI.md) for all commands, first-run setup,
configuration, exit codes, deadlines, and troubleshooting.

## Requirements

- For Obsidian app workflows: [Obsidian](https://obsidian.md/) with CLI enabled
  (`Settings → General → Command line interface`)
- For those app workflows, enable these settings:
  - **Use [[Wikilinks]]** (`Settings → Files and Links`)
  - **Automatically update internal links** (`Settings → Files and Links`)
- A supported agent host: Claude Code, Codex, or Hermes (optional for CLI-only use)
- Python 3.12 or newer for the standalone CLI; the Obsidian app need not be running.
- [`uv`](https://docs.astral.sh/uv/) on `PATH` — recommended for CLI installation
  and required by `scan-vault-secrets.py` and the Hermes integration
- [Ollama](https://ollama.com/) installed and running locally, with the
  `bge-m3` embedding model pulled. Optional; enables semantic search.
  Without it, setup and search use local keyword indexing with no embedding requests.
  Ollama is a separate server; the PyPI `ollama` package is only a client and
  does not install the server or model.

## Installation

```bash
# 1. Install the CLI
uv tool install obsidian-knowledge

# 2. Run setup (registers vault, installs claude plugin if available, initial reindex)
obsidian-knowledge setup --vault /path/to/your/obsidian/vault

# 3. Install Ollama and pull the default embedding model (optional — improves search ranking)
brew install ollama          # macOS; or see ollama.com/download
brew services start ollama   # macOS; on Linux, start your installed Ollama service
ollama pull bge-m3
obsidian-knowledge reindex --vault /path/to/your/obsidian/vault
```

`setup` is idempotent — safe to re-run. If `claude` is not on `PATH`, the plugin install step is skipped automatically.
Use `--skip-claude-plugin` to explicitly skip it for CLI-only, Codex, or Hermes
setup. The vault directory must already exist. Malformed registry/configuration
files and failed plugin installations report errors instead of claiming success.
Setup defaults to a 300-second deadline; increase `--timeout-seconds` for a large
first index. Verify your own notes with `obsidian-knowledge doctor --query "known phrase"`.

Upgrade the CLI with `uv tool upgrade obsidian-knowledge`.

Python 3.12, 3.13, and 3.14 are tested. `uv tool install` selects Python
automatically; no `--python` override is required. CI also installs the built
wheel into a fresh tool environment and verifies setup and search without Ollama.

PyPI publishing runs after successful push CI on `main`, including docs-only
changes. An unpublished manual version is preserved; otherwise the latest patch
version is incremented. The release synchronizes Python, Claude, Codex, and Hermes
versions, reruns checks, and commits the version before uploading. Tags are not
required. Superseded CI runs defer to the newer push; failed uploads can be retried
without another bump. The bot's version commit does not trigger another CI run.

The protection hooks use `vaults.yaml` to know which directories to guard.
Without it, the `_sources/`, published-file, and destructive-ops rules will
not fire.

### Codex installation

After installing the CLI and registering the vault above, install the Codex plugin:

```bash
codex plugin marketplace add crypdick/obsidian-knowledge
codex plugin add obsidian-knowledge@obsidian-knowledge
```

Restart Codex and review plugin enablement and hook trust through `/plugins` or
`/hooks`. For local development, use the control checkout and reinstall workflow
in [AGENTS.md](https://github.com/crypdick/obsidian-knowledge/blob/main/AGENTS.md).

### Global Codex sandbox access

Installing the plugin does not grant sandbox access. For sessions using
`workspace-write`, merge the following into `~/.codex/config.toml`. It applies
across repositories without selecting a dedicated permission profile. Replace
the example paths with absolute paths to your vault and [host cache](#cache-location).
Keep existing writable roots and domain rules; merge existing TOML tables rather
than declaring them twice. If `features.network_proxy` is already a boolean,
replace it with the table form below.

```toml
[sandbox_workspace_write]
writable_roots = [
  "/path/to/obsidian/vault/wiki",
  "/path/to/obsidian/vault/Utility/obsidian-knowledge",
  "/home/your-user/.cache/obsidian-knowledge",
]
network_access = true

[features.network_proxy]
enabled = true

[features.network_proxy.domains]
"127.0.0.1" = "allow"
"localhost" = "allow"
```

The writable directories cover notes, papercut logs and their lock files,
changelog fragments, and the search cache. On macOS, use
`/Users/your-user/Library/Caches/obsidian-knowledge` for the cache entry. Run initial
`setup` from a terminal with vault access; these grants cover routine memory work,
not edits throughout every vault folder.

Keep the proxy enabled: `network_access = true` alone permits unrestricted command
network access. With the proxy active, this example allows localhost destinations
and blocks public destinations; add other required hosts to your existing policy
explicitly. The allowlist is host-based, not limited to Ollama's port. See the
[Codex configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference).

These settings use Codex's `sandbox_workspace_write` configuration. Deployments
that enforce named permission profiles must configure the equivalent grants in
their active policy; the two permission systems do not compose. See
[Codex permissions](https://learn.chatgpt.com/docs/permissions).

Restart Codex and open a new session after changing permissions. Verify from the
repository where you normally work, using a phrase from an indexed note:

```bash
codex sandbox -c 'sandbox_mode="workspace-write"' -- obsidian-knowledge search "known note phrase"
codex sandbox -c 'sandbox_mode="workspace-write"' -- python3 -c 'import tempfile; tempfile.TemporaryFile(dir="/path/to/obsidian/vault/wiki").close()'
```

The first command should return matching notes without `ranking degraded`; the
second should exit successfully and leaves no note behind. These checks were
verified on Linux with Codex 0.153.4. In that version, inherit the shell's working
directory: adding `codex sandbox -C` requires a named profile. A successful search
from an unrestricted terminal alone does not verify sandbox access.

### Ollama service availability

Check Ollama from a normal terminal before diagnosing startup:

```bash
curl --fail http://127.0.0.1:11434/api/tags
```

On Linux, inspect an installed user service with `systemctl --user status ollama`
and `journalctl --user -u ollama`; omit `--user` for a system service. A user service
normally starts at login. To run an enabled user service from boot and while logged
out, enable lingering with `sudo loginctl enable-linger "$USER"`. Running
`ollama serve` directly only runs the server in that process; it does not install
or enable a service. A sandbox connection error reporting `EPERM` or `EACCES` is
an access restriction and does not establish a startup failure.

### Switching embedding models

Override any of the defaults via environment variables:

| Variable | Default | Purpose |
|---|---|---|
| `MEMWEAVE_EMBEDDING_MODEL` | `ollama/bge-m3` | LiteLLM model identifier |
| `MEMWEAVE_EMBEDDING_API_BASE` | `http://127.0.0.1:11434` | Ollama / LiteLLM endpoint |
| `MEMWEAVE_EMBEDDING_API_KEY` | unset | API key (leave unset for Ollama) |

When the embedding model changes, the next `obsidian-knowledge search` call detects the
mismatch and rebuilds the index automatically. The fingerprint
(`<model>@<chunk-tokens>/<chunk-overlap>`) is stored alongside the index.

### Cache location

The embedding DB lives outside the vault, in the per-host XDG cache
directory:

| OS | Path |
|---|---|
| Linux | `${XDG_CACHE_HOME:-~/.cache}/obsidian-knowledge/<vault-key>/` |
| macOS | `~/Library/Caches/obsidian-knowledge/<vault-key>/` |

`<vault-key>` is `<vault-dir-name>-<sha256(absolute_path)[:8]>`, so two vaults
named `obsidian/` on different machines (or in different parents) never
collide. Each host owns its own embeddings DB — Syncthing and other vault
sync tools never see it, eliminating cross-device write conflicts.

A pre-3.16 install with the old in-vault cache (`<vault>/.config/obsidian-knowledge/cache/`)
will trigger one auto-rebuild on first use. The old directory is safe to
delete once the new cache is populated.

### Keeping the index fresh

There is no built-in file-watcher. Content added or edited between reindexes
is invisible to `obsidian-knowledge search` until the next reindex. An hourly cron is
the recommended baseline:

```cron
# Linux
0 * * * * $HOME/.local/bin/obsidian-knowledge reindex --vault $HOME/Documents/obsidian --timeout-seconds 300 >> $HOME/.cache/obsidian-knowledge/cron.log 2>&1

# macOS (Apple Silicon)
0 * * * * $HOME/.local/bin/obsidian-knowledge reindex --vault $HOME/Documents/obsidian --timeout-seconds 300 >> $HOME/Library/Caches/obsidian-knowledge/cron.log 2>&1
```

Incremental reindex is cheap: ~8s wall on a ~1700-file vault with zero
edits (all files hash-skip). Only modified files get re-embedded. Overlap
is guarded by an `fcntl.flock` on `<cache>/.reindex.lock` — a second run
that fires while the first is still active exits cleanly without
touching the DB.

## Usage

Invoke the skill directly:

> Organize my vault / update indexes / fix broken links / rename ambiguous
> files / garden the vault

Or set up a scheduled run for routine maintenance.

The skill stores its state in your vault at
`Utility/obsidian-knowledge/`:

- `changelog/` — terse same-session audit pointers created only after durable vault mutations
- `needs-attention.md` — human-resolved worklist
- `reports/open-questions.md` — regenerated dashboard of `> [!question]` callouts

Historical state was under `.config/obsidian-knowledge/` prior to v1.1.0.

### Vault configuration

For best results, add a `CLAUDE.md` to your vault root with naming
conventions and instructions to invoke the skill after structural edits.

The vault-organizer respects access zones defined in
`.claude/vault-zones.yaml`. Create this file to control which folders
the agent can organize, where indexes are required, and which areas
are read-only. See the skill's documentation for the expected format.

## License

MIT
