---
name: vault-organizer
description: >-
  This skill should be used when the user asks to "organize the vault",
  "update indexes", "fix broken links", "rename ambiguous files", "fix
  filenames", "garden the vault", "sync indexes", "clean up the vault",
  "maintain the vault", or after making substantial structural edits
  (creating, moving, renaming, or deleting files) in an Obsidian vault.
  Also triggered by scheduled cron invocations for routine vault maintenance.
version: 1.4.10
---

# Vault organizer

Maintain indexes, links, locations, and filenames. Preserve primary note
content except for the link and frontmatter repairs described here. Read each
`lib/` reference only when its step applies. Triage every issue, including
existing ones. Process large lists in batches without skipping the remainder.

## Prerequisites

- Install and configure the Obsidian CLI in
  **Settings > General > Command line interface**.
- Enable **Use [[Wikilinks]]** and **Automatically update internal links** in
  Obsidian settings.
- Always pass `vault="<name>"` before the subcommand, as in
  `obsidian vault="<name>" <command> ...`. Replace `<name>` with the registered
  vault name and `<command>` with the subcommand. The `vault` option is global.
  After the subcommand, the CLI can silently ignore it and write to the wrong
  vault while still reporting success.
- Write index, report, state, and changelog Markdown with
  `obsidian-knowledge write` and a quoted heredoc. Read existing files first and
  use `--replace` for full-file updates. Require `Wrote and verified:`. Complete
  the primary note or move first, verify it, then update dependent indexes.

## Sync-conflict exclusion

Exclude Syncthing `.sync-conflict-YYYYMMDD-HHMMSS-DEVICEID` files from all
maintenance and reports. Handle them separately as conflict merge or deletion
work; they are not live notes.

## Pipeline

### Locate the vault

Set `VAULT` to the configured filesystem root and `VAULT_NAME` to its registered
Obsidian name. Set `VAULT_ORGANIZER_DIR` to the directory containing this loaded
`SKILL.md`, using the skill path supplied by the runtime. Scripts and `lib/` live
beside it in both source and installed copies. Do not infer that directory from
the working directory or search for an arbitrary installed copy.

```bash
cat ~/.config/obsidian-knowledge/vaults.yaml   # get VAULT path
cat "$VAULT/CLAUDE.md"                          # naming conventions
cat "$VAULT/.claude/obsidian-knowledge.yaml"    # zone config
obsidian vault="${VAULT_NAME:?set the registered vault name}" version
```

### Read state

Read `$VAULT/Utility/obsidian-knowledge/needs-attention.md` to identify known and
resolved issues.

### Run the structural audit

```bash
SCRIPTS="${HERMES_VAULT_ORGANIZER_SCRIPTS:-${VAULT_ORGANIZER_DIR:?set the loaded skill directory}}"
if [ ! -f "$SCRIPTS/vault-audit.py" ]; then
  printf 'Missing vault-audit.py in %s; check the loaded skill path or explicit override.\n' "$SCRIPTS" >&2
  exit 1
fi
uv run --no-project --with pyyaml python "$SCRIPTS/vault-audit.py" "$VAULT"
```

Use the issue codes to select the repair instructions.

### Fix structural issues

**`MISSING_INDEX <folder>`**: Create `index.md`. Read `lib/index-format.md`.

**`NOT_INDEXED <index> entry=<name>`**: Add the entry. Read `lib/index-format.md`.

**`DUMPING_GROUND <folder> misplaced=N inline_total=T subfolders=M`**: Classify
the misplaced inline files, which have date prefixes or `*-design`, `*-convo`,
or `*-diary` names, and move them to typed subfolders. Read `lib/note-types.md`
and `lib/index-format.md`.

**`STACKED_FRONTMATTER <file>`**: Fix stray duplicate `---` markers. Replace
`NOTE_PATH` with the note's filesystem path. You can pass multiple paths:

```bash
uv run --no-project --with pyyaml python "$SCRIPTS/fix-stacked-frontmatter.py" --fix NOTE_PATH
```

Files reported as `NEEDS_MERGE` contain a second block with keys and require a
manual merge. Read `lib/stacked-frontmatter.md`.

After structural fixes, rename ambiguous non-Markdown files. Read `lib/rename-files.md`.

### Fix broken links

```bash
obsidian vault="$VAULT_NAME" unresolved verbose format=json | uv run --no-project --with pyyaml python "$SCRIPTS/filter-unresolved-links.py" "$VAULT"
obsidian vault="$VAULT_NAME" unresolved verbose format=json | uv run --no-project --with pyyaml python "$SCRIPTS/recover-unresolved-links.py" "$VAULT" > /tmp/vault-unresolved-recovery.tsv
obsidian vault="$VAULT_NAME" orphans
```

Read [broken-link triage](lib/broken-links.md) for each remaining candidate.
Review the recovery report before using `recover-unresolved-links.py --apply`;
it changes only unique, high-confidence matches.

### Fix convention violations

```bash
uv run --no-project --with pyyaml python "$SCRIPTS/convention-sweep.py" "$VAULT"
```

The output is tab-separated, with one issue per line:

```text
WIKILINK_EXT  <rel_path>:<line>  <match>     # [[foo.md]] → should be [[foo]]
UNDATED_FILE  <rel_path>                     # in Journal/diary/convos/plans without YYYY-MM-DD prefix
YAML_ERR      <rel_path>         <error>     # malformed frontmatter
```

Rename undated files with `obsidian vault="$VAULT_NAME" rename`, remove
`.md` from wikilinks, and repair malformed frontmatter. Record unresolved issues
in `needs-attention.md` using [state-file conventions](lib/state-files.md).
Only the organizer writes this worklist.

### Regenerate reports

Rewrite `$VAULT/Utility/obsidian-knowledge/reports/open-questions.md` from scratch:

```bash
uv run --no-project --with pyyaml python "$SCRIPTS/find-open-questions.py" "$VAULT"
```

Output is `<rel_path>\t<line>\t<question_text>` per question. Code-block examples
are filtered automatically. Build one entry per line:
`- [[wiki/path/to/page]] — line N — "question text"`

Preserve the existing heading, regeneration notice, and scope section. Change
only the entry list and `Last run:` timestamp.

### Update the worklist

Remove resolved entries. Add new unresolvable issues. Read `lib/state-files.md` for format.

### Record completed changes

Create `$VAULT/Utility/obsidian-knowledge/changelog/YYYY-MM-DD-HHMMSS-<slug>.md`. Read `lib/state-files.md` for format. Do not edit a shared changelog index; per-session files are the concurrency-safe audit record. Skip this step if you took no actions.
