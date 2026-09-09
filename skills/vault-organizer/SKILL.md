---
name: vault-organizer
description: >-
  This skill should be used when the user asks to "organize the vault",
  "update indexes", "fix broken links", "rename ambiguous files", "fix
  filenames", "garden the vault", "sync indexes", "clean up the vault",
  "maintain the vault", or after making substantial structural edits
  (creating, moving, renaming, or deleting files) in an Obsidian vault.
  Also triggered by scheduled cron invocations for routine vault maintenance.
version: 1.4.9
---

# Vault organizer

Maintain indexes, links, locations, and filenames. Preserve primary note
content except for the link and frontmatter repairs described here. Read each
`lib/` reference only when its step applies. Triage every issue, including
pre-existing ones; process large lists in batches without skipping the remainder.

## Prerequisites

- Obsidian CLI installed and configured (`Settings → General → Command line interface`)
- **Use [[Wikilinks]]** and **Automatically update internal links** enabled in Obsidian settings
- Always pass `vault="<name>"` before the subcommand (`obsidian vault="<name>" <command> ...`). It is a global option; after the subcommand it can be silently ignored, causing a wrong-vault write that still reports success.
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

Read `$VAULT/Utility/obsidian-knowledge/needs-attention.md` — note known issues, detect resolved ones.

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

**`MISSING_INDEX <folder>`** — create index.md. Read `lib/index-format.md`.

**`NOT_INDEXED <index> entry=<name>`** — add entry. Read `lib/index-format.md`.

**`DUMPING_GROUND <folder> misplaced=N inline_total=T subfolders=M`** — classify the misplaced inline files (date-prefixed and `*-design`/`-convo`/`-diary`), move them to typed subfolders. Read `lib/note-types.md` + `lib/index-format.md`.

**`STACKED_FRONTMATTER <file>`** — auto-fix stray duplicate `---` markers:

```bash
uv run --no-project --with pyyaml python "$SCRIPTS/fix-stacked-frontmatter.py" --fix <file1> <file2> ...
```

Files reported as `NEEDS_MERGE` (real second block with keys) require manual merge — read `lib/stacked-frontmatter.md`.

After structural fixes, rename ambiguous non-markdown files. Read `lib/rename-files.md`.

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

Output (tab-separated, one issue per line):

```
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

Preserve existing file structure (heading, regeneration notice, scope section). Only entry list + `Last run:` timestamp change.

### Update the worklist

Remove resolved entries. Add new unresolvable issues. Read `lib/state-files.md` for format.

### Record completed changes

Create `$VAULT/Utility/obsidian-knowledge/changelog/YYYY-MM-DD-HHMMSS-<slug>.md`. Read `lib/state-files.md` for format. Do not edit a shared changelog index; per-session files are the concurrency-safe audit record. Skip if no actions taken.
