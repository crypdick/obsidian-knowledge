---
name: vault-organizer
description: >-
  This skill should be used when the user asks to "organize the vault",
  "update indexes", "fix broken links", "rename ambiguous files", "fix
  filenames", "garden the vault", "sync indexes", "clean up the vault",
  "maintain the vault", or after making substantial structural edits
  (creating, moving, renaming, or deleting files) in an Obsidian vault.
  Also triggered by scheduled cron invocations for routine vault maintenance.
version: 1.5.1
---

# Vault organizer

Maintain indexes, links, filenames, and note locations. Preserve primary note
content except for intended link and frontmatter repairs. Read each `lib/`
reference only when its step applies.

## Setup

Use the installed `obsidian-knowledge garden` commands. After setup, they use
the configured default vault without environment variables or flags. All note
paths are vault-relative.

Before Obsidian operations, check `obsidian vault info=path` matches the vault
being maintained. For another vault or mismatched CLI targets, read
[multi-vault selection](lib/multi-vault.md).

Read the vault's local instructions, `.claude/obsidian-knowledge.yaml`, and
`Utility/obsidian-knowledge/needs-attention.md`. Enable automatic internal-link
updates in Obsidian.

Exclude hidden files, protected sources, and Syncthing sync conflicts from
maintenance. Handle conflicts separately. Repairs refuse existing published
notes; use the manual edit and human-consent workflow. Use `obsidian-knowledge
write` for manual Markdown edits; its writer verifies the result.

## Structure

```bash
obsidian-knowledge garden audit
```

Triage all findings:

- `MISSING_INDEX`, `NOT_INDEXED`: create or complete indexes using
  [index conventions](lib/index-format.md). Read children to write useful
  orientation phrases; a descendant link does not replace a child-index link.
- `EMPTY_FOLDER`: check sync state and local layout. Do not create empty indexes
  or delete folders automatically.
- `DUMPING_GROUND`: classify misplaced dated, design, diary, and conversation
  notes by meaning. Follow [note locations](lib/note-types.md).
- `STACKED_FRONTMATTER`: use `obsidian-knowledge garden frontmatter --apply NOTE_PATH`.
  `NEEDS_MERGE` requires [manual frontmatter repair](lib/stacked-frontmatter.md).

Rename ambiguous files using [rename guidance](lib/rename-files.md).
Use Obsidian move and rename commands so internal links update.

## Links

```bash
obsidian unresolved verbose format=json | obsidian-knowledge garden links
```

Inspect the report. Add `--apply` for unique recoveries; triage remaining links
using [broken-link guidance](lib/broken-links.md). Preserve aliases, headings,
block references, and primary text. Leave intentional concept stubs intact.

```bash
obsidian orphans
```

Add managed notes to their parent indexes where appropriate. Respect established
exceptions and ignore orphans outside managed zones.

## Question report

```bash
obsidian-knowledge garden questions --apply
```

Fix `WIKILINK_EXT` (`.md` in note links), `UNDATED_FILE` (missing required date
prefix), and `YAML_ERR` from the audit. The question report defaults to
`Utility/obsidian-knowledge/reports/open-questions.md`, preserving its header,
frontmatter, and scope. Use `--report` to preview or `--timestamp` to override
current local time. With no flags, the scanner emits TSV.

## Finish

Re-run affected checks. Review changed links and fresh CLI results; reload
Obsidian only if its cache disagrees with file contents. No checksum comparison
is needed for an ordinary CLI move or rename.

Update unresolved items in `needs-attention.md` and record completed vault
changes in one same-session changelog fragment. Follow [state-file conventions](lib/state-files.md);
do not edit a shared changelog index. Skip logging when no vault changes occurred.
