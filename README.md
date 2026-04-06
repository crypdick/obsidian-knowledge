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
- **Report issues** — maintains a `NEEDS_ATTENTION.md` worklist for issues
  requiring human judgment

### remember-conversations

Files valuable conversation outputs as permanent vault notes and updates
the changelog, so insights compound rather than disappearing into chat
history:

- **Session notes** — two types: `-diary` for narrative accounts (what
  happened, what was tried) and `-convo` for analytical synthesis
  (comparisons, decision rationales, research summaries)
- **Changelog updates** — appends a dated entry to CHANGELOG.md
  summarizing actions taken
- **Automatic placement** — notes filed in `sessions/` subfolders within
  the relevant subtree, preserving progressive disclosure
- **Stop hook integration** — a reminder nudges the agent to file
  sessions at the end of each conversation

## Hooks

### Vault protection (PreToolUse)

`protect-vault.py` runs before every Bash, Write, and Edit tool call.
It provides two layers of safety:

**Read-only `_sources/` directories.** Folders named `_sources/` anywhere
in the vault tree are protected from agent writes. These typically hold
irreplaceable originals (tax records, legal filings, vital docs, property
deeds). Agents can read them to generate summaries and indexes, but cannot
create, modify, rename, move, or delete files inside them.

**Destructive command guards.** Recursive `rm` and `mv` targeting paths
that appear to be inside an Obsidian vault are blocked.

**Escape hatch.** Prefix a Bash command with `I_AM_BEING_CAREFUL=1` to
bypass all guards after the user explicitly confirms. Write/Edit to
`_sources/` has no inline bypass — use Bash with the escape hatch.

### Stop hooks

Both Stop hooks fire at the end of each Claude Code turn. Each walks up
from `$PWD` looking for a `.obsidian/` directory to detect whether the
agent is working inside a vault. They have a 5-minute cooldown per
session to avoid being noisy in long conversations.

- **update-changelog.sh** — reminds the agent to append a dated entry to
  `CHANGELOG.md` if the session produced edits, decisions, or discoveries
- **remind-convos.sh** — reminds the agent to preserve session outputs
  (diary notes, convo notes, guides, changelog entries, gotchas)

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

## Usage

Invoke the skill directly:

> Organize my vault / update indexes / fix broken links / rename ambiguous
> files / garden the vault

Or set up a scheduled run for routine maintenance.

The skill stores its state in your vault at
`.config/obsidian-knowledge/` (CHANGELOG.md and NEEDS_ATTENTION.md).

### Vault configuration

For best results, add a `CLAUDE.md` to your vault root with naming
conventions and instructions to invoke the skill after structural edits.

The vault-organizer respects access zones defined in
`.claude/vault-zones.yaml`. Create this file to control which folders
the agent can organize, where indexes are required, and which areas
are read-only. See the skill's documentation for the expected format.

## License

MIT
