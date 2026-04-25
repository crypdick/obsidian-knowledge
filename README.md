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
- **Changelog updates** — appends a dated entry to `changelog.md`
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
other tools, and vault search. The hook redirects this knowledge to the
vault wiki instead, where it compounds and stays searchable.

**Escape hatch.** Prefix a Bash command with `I_AM_BEING_CAREFUL=1` to
bypass the `_sources/` and published-file guards after the user explicitly
confirms. The auto-memory redirect has no escape hatch — write to the wiki
instead.

### Stop hooks

Both Stop hooks fire at the end of each Claude Code turn. Each checks
whether the working directory is inside a configured vault root. They
have a 5-minute cooldown per session to avoid being noisy in long
conversations.

- **update-changelog.sh** — reminds the agent to append a dated entry to
  `changelog.md` if the session produced edits, decisions, or discoveries
- **remind-convos.sh** — reminds the agent to preserve session outputs
  (diary notes, convo notes, guides, changelog entries, gotchas)

### recall-init (SessionStart)

`recall-init.py` runs at every session start. Two responsibilities:

1. **Verify the memory symlink.** Checks that `~/.claude/projects/` is
   symlinked to `<vault-root>/wiki/systems/repos/`. If not, emits a
   non-blocking warning telling the user to run `/setup-harness`.
2. **Inject the harness primer.** Adds a 5-directive context block to
   the session: memory location, recall via `rg`, capture at session
   end, friction reflection, user-frustration reflection. The primer
   stands alone — agents that read only this know how to operate
   within the harness.

### reflect-nudge (PostToolUse on Bash)

`reflect-nudge.py` fires every 10 bash invocations within a session.
Continuous — no per-session suppression. Reminds the agent to step back
and consider whether observed friction warrants a harness improvement.

## Commands

### /setup-harness

One-time migration. Rsyncs `~/.claude/projects/*` into
`<vault>/wiki/systems/repos/`, surfaces collisions for manual merge,
then replaces `~/.claude/projects/` with a symlink. Idempotent re-runs
are safe.

### /improve-harness <description>

Triggers the meta-improvement workflow. The argument is the friction
description — main agent uses it to seed the incident report and
generate a slug.

## Requirements

- [Obsidian](https://obsidian.md/) with CLI enabled
  (`Settings → General → Command line interface`)
- The following Obsidian settings must be enabled:
  - **Use [[Wikilinks]]** (`Settings → Files and Links`)
  - **Automatically update internal links** (`Settings → Files and Links`)
- [Claude Code](https://docs.anthropic.com/en/docs/claude-code) with plugin
  support

## Installation

```bash
# Add the marketplace
claude plugin marketplace add crypdick/obsidian-knowledge

# Install the plugin
claude plugin install obsidian-knowledge@obsidian-knowledge
```

After installing, create `~/.config/obsidian-knowledge/vaults.yaml` listing
your vault root paths:

```yaml
vaults:
  - /path/to/your/obsidian/vault
```

The protection hooks use this file to know which directories to guard. Without
it, the `_sources/`, published-file, and destructive-ops rules will not fire.

## Usage

Invoke the skill directly:

> Organize my vault / update indexes / fix broken links / rename ambiguous
> files / garden the vault

Or set up a scheduled run for routine maintenance.

The skill stores its state in your vault at
`Utility/obsidian-knowledge/`:

- `changelog.md` — append-only log of vault changes
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
