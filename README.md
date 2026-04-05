# Obsidian Knowledge

A Claude Code plugin marketplace with skills and hooks for maintaining
Obsidian knowledge base vaults.

## Skills

### vault-organizer

Maintains vault organization through a single-pass pipeline:

- **Sync indexes** — creates and updates `index.md` files with thin pointer
  entries for every folder
- **Organize files** — moves misplaced files to appropriate locations using
  the Obsidian CLI
- **Rename ambiguous files** — detects files with non-descriptive names
  (device-generated, hash-based, generic labels), reads their content, and
  renames them to `yyyy-mm-dd-descriptive-slug.ext`
- **Fix broken links** — detects unresolved links and resolves them when
  possible, flags ambiguous cases for human review
- **Report issues** — maintains a `NEEDS_ATTENTION.md` worklist for issues
  requiring human judgment

### remember-conversations

Files valuable conversation outputs as permanent vault notes so insights
compound rather than disappearing into chat history:

- **Analyses, comparisons, decision rationales** — anything worth finding later
- **Automatic placement** — notes filed in `convos/` subfolders within the
  relevant subtree, preserving progressive disclosure
- **Stop hook integration** — a reminder nudges the agent to file conversations
  at the end of each session

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

Both Stop hooks fire at the end of each Claude Code session. Each walks up
from `$PWD` looking for a `.obsidian/` directory to detect whether the
agent is working inside a vault. They fire once per session to avoid
re-triggering loops.

- **update-changelog.sh** — reminds the agent to append a dated entry to
  `CHANGELOG.md` if the session produced edits, decisions, or discoveries
- **remind-convos.sh** — reminds the agent to use the
  `remember-conversations` skill to file valuable conversation outputs

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

### Vault CLAUDE.md

For best results, add a `CLAUDE.md` to your vault root instructing agents
to invoke the skill after substantial structural edits:

```markdown
After making substantial edits to this vault (creating, moving, renaming,
or deleting files), invoke the vault-organizer skill to update indexes
and verify link integrity.
```

## License

MIT
