---
name: vault-organizer
description: >-
  This skill should be used when the user asks to "organize the vault",
  "update indexes", "fix broken links", "rename ambiguous files", "fix
  filenames", "garden the vault", "sync indexes", "clean up the vault",
  "maintain the vault", or after making substantial structural edits
  (creating, moving, renaming, or deleting files) in an Obsidian vault.
  Also triggered by scheduled cron invocations for routine vault maintenance.
version: 1.4.12
---

# Vault organizer

Maintain indexes, links, filenames, and note locations. Preserve primary note
content except for intended link and frontmatter repairs. Read each `lib/`
reference only when its step applies.

## Setup

Set `SCRIPTS` to the directory containing the loaded `SKILL.md`. Use that copy,
not an arbitrary plugin cache or the working directory. Scripts declare their
own dependencies; run them with `uv run`.

Scripts default to the configured vault containing cwd, or the sole registered
vault. Pass a vault root as the first argument to override it. When multiple
vaults are configured and cwd selects none, an explicit root is required.

Read the vault's local instructions, `.claude/obsidian-knowledge.yaml`, and
`Utility/obsidian-knowledge/needs-attention.md`. Set `VAULT_NAME` to its registered
Obsidian name. Keep `vault="$VAULT_NAME"` before every Obsidian subcommand; after
it, the CLI can silently ignore the option. Enable automatic internal-link
updates in Obsidian.

Exclude hidden files, protected sources, and Syncthing sync conflicts from
maintenance. Handle conflicts separately. Use `obsidian-knowledge write` for
manual Markdown edits; its writer verifies the result. Helpers already use it.

## Structure

```bash
uv run "$SCRIPTS/vault-audit.py"
```

Triage all findings:

- `MISSING_INDEX`, `NOT_INDEXED`: create or complete indexes using
  [index conventions](lib/index-format.md). Read children to write useful
  orientation phrases; a descendant link does not replace a child-index link.
- `EMPTY_FOLDER`: check sync state and local layout. Do not create empty indexes
  or delete folders automatically.
- `DUMPING_GROUND`: classify misplaced dated, design, diary, and conversation
  notes by meaning. Follow [note locations](lib/note-types.md).
- `STACKED_FRONTMATTER`: use `uv run "$SCRIPTS/fix-stacked-frontmatter.py" --fix NOTE_PATH`.
  `NEEDS_MERGE` requires [manual frontmatter repair](lib/stacked-frontmatter.md).

Rename ambiguous files using [rename guidance](lib/rename-files.md).
Use Obsidian move and rename commands so internal links update.

## Links

```bash
obsidian vault="$VAULT_NAME" unresolved verbose format=json | uv run "$SCRIPTS/recover-unresolved-links.py"
```

Inspect the report. Add `--apply` for unique recoveries; triage remaining links
using [broken-link guidance](lib/broken-links.md). Preserve aliases, headings,
block references, and primary text. Leave intentional concept stubs intact.

```bash
obsidian vault="$VAULT_NAME" orphans
```

Add managed notes to their parent indexes where appropriate. Respect established
exceptions and ignore orphans outside managed zones.

## Conventions and reports

```bash
uv run "$SCRIPTS/convention-sweep.py"
uv run "$SCRIPTS/find-open-questions.py" --apply
```

Fix `WIKILINK_EXT` (`.md` in note links), `UNDATED_FILE` (missing required date
prefix), and `YAML_ERR`. The question report defaults to
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
