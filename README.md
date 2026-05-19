# Obsidian Knowledge

A Claude Code plugin marketplace with skills and hooks for maintaining
Obsidian knowledge base vaults.

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

Files valuable conversation outputs as permanent vault notes and updates
the changelog, so insights compound rather than disappearing into chat
history:

- **Session notes** — two types: `-diary` for narrative accounts (what
  happened, what was tried) and `-convo` for analytical synthesis
  (comparisons, decision rationales, research summaries)
- **Changelog updates** — creates a terse per-session file in `changelog/`
  summarizing actions taken
- **Automatic placement** — notes filed in `sessions/` subfolders within
  the relevant subtree, preserving progressive disclosure
- **Stop hook integration** — a reminder nudges the agent to file
  sessions at the end of each conversation

### improve-harness

Multi-phase side-quest workflow to fix harness friction. Triggered by
`/improve-harness <description>` or natural-language frustration phrases.
The side quest runs as a headless `claude -p --worktree` session that
produces a proposal (with internal review), receives main-agent
executive review, then implements (with internal review via
`subagent-driven-development`) and leaves a branch for human approval.

The skill is organized for progressive disclosure: `SKILL.md` is a thin
index; sub-asset files (`phases.md`, `templates.md`, `conventions.md`)
hold the details and load only when needed.

### deploy-harness

Single-purpose skill: merge an approved `improve/<slug>` branch into
main, bump patch version, push to origin. Called from `improve-harness`
Phase 5 or invokable manually.

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

Stop hooks fire at the end of each Claude Code turn. Each checks
whether the working directory is inside a configured vault root. They
have a 5-minute cooldown per session to avoid being noisy in long
conversations.

- **update-changelog.py** — reminds the agent to create a per-session file in
  `changelog/` if the session produced edits, decisions, or discoveries
- **remind-convos.py** — reminds the agent to preserve session outputs
  (diary notes, convo notes, guides, changelog entries, gotchas)
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
primer: a 5-directive context block covering memory location, recall
via `obsidian-knowledge search`, capture at session end, friction reflection, and
user-frustration reflection. The primer stands alone — agents that
read only this know how to operate within the harness.

### reflect-nudge (PostToolUse on Bash)

`reflect-nudge.py` fires every 10 bash invocations within a session.
Continuous — no per-session suppression. Reminds the agent to step back
and consider whether observed friction warrants a harness improvement.

## Commands

### /improve-harness <description>

Triggers the meta-improvement workflow. The argument is the friction
description — main agent uses it to seed the incident report and
generate a slug.

### obsidian-knowledge search "<query>"

Searches the indexed `wiki/` tree and returns ranked `score  path` lines.
Pass `--all` to include normally-hidden zones (`Inbox/`, `Journal/`).

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

## Requirements

- [Obsidian](https://obsidian.md/) with CLI enabled
  (`Settings → General → Command line interface`)
- The following Obsidian settings must be enabled:
  - **Use [[Wikilinks]]** (`Settings → Files and Links`)
  - **Automatically update internal links** (`Settings → Files and Links`)
- [Claude Code](https://docs.anthropic.com/en/docs/claude-code) with plugin
  support
- [`uv`](https://docs.astral.sh/uv/) on `PATH` — required by
  `scan-vault-secrets.py` and the `obsidian-knowledge` CLI
- [Ollama](https://ollama.com/) installed and running locally, with the
  `bge-m3` embedding model pulled. Optional; enables better search ranking.

## Installation

```bash
# 1. Install the CLI
uv tool install obsidian-knowledge

# 2. Run setup (registers vault, installs claude plugin if available, initial reindex)
obsidian-knowledge setup --vault /path/to/your/obsidian/vault

# 3. Install Ollama and pull the default embedding model (optional — improves search ranking)
brew install ollama          # macOS; or see ollama.com/download
brew services start ollama   # macOS; on Linux: `ollama serve` (systemd)
ollama pull bge-m3
```

`setup` is idempotent — safe to re-run. If `claude` is not on `PATH`, the plugin install step is skipped automatically.

The protection hooks use `vaults.yaml` to know which directories to guard.
Without it, the `_sources/`, published-file, and destructive-ops rules will
not fire.

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
0 * * * * $HOME/.local/bin/obsidian-knowledge reindex --vault $HOME/Documents/obsidian >> $HOME/.cache/obsidian-knowledge/cron.log 2>&1

# macOS (Apple Silicon)
0 * * * * $HOME/.local/bin/obsidian-knowledge reindex --vault $HOME/Documents/obsidian >> $HOME/Library/Caches/obsidian-knowledge/cron.log 2>&1
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

- `changelog/` — per-session terse logs (one file per agent session, 1-liners only)
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
