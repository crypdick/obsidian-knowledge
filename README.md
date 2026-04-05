# Obsidian Knowledge Base Skills

A Claude Code plugin marketplace with skills for maintaining Obsidian
knowledge base vaults.

## Skills

### vault-organizer

Maintains vault organization through a single-pass pipeline:

- **Sync indexes** — creates and updates `index.md` files with thin pointer
  entries for every folder
- **Organize files** — moves misplaced files to appropriate locations using
  the Obsidian CLI
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
/plugin marketplace add crypdick/obsidian-knowledge-base-skill

# Install the plugin
/plugin install obsidian-knowledge-base-skill@obsidian-knowledge-base-skill
```

## Usage

Invoke the skill directly:

> Organize my vault / update indexes / fix broken links / garden the vault

Or set up a scheduled run for routine maintenance.

The skill stores its state in your vault at
`.config/obsidian-knowledge-base-skill/` (CHANGELOG.md and
NEEDS_ATTENTION.md).

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
