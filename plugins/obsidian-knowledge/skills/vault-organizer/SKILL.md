---
name: vault-organizer
description: >-
  This skill should be used when the user asks to "organize the vault",
  "update indexes", "fix broken links", "rename ambiguous files", "fix
  filenames", "garden the vault", "sync indexes", "clean up the vault",
  "maintain the vault", or after making substantial structural edits
  (creating, moving, renaming, or deleting files) in an Obsidian vault.
  Also triggered by scheduled cron invocations for routine vault maintenance.
version: 1.4.7
---

# Vault Organizer

Maintain Obsidian vault structure. Single-pass pipeline. Never edit primary file content — only indexes, links, locations, names.

**Don't read lib/ files upfront. Fetch them only when you hit that step.**

**Pre-existing issues are in scope.** This skill exists to fix accumulated problems, not just ones introduced since the last run. If something was broken before today, it is still broken and still your job to triage. Volume is not an exit condition — a 700-item unresolved-link list is the *most* important pass to actually walk, not the one to dismiss as "mostly stubs." Triage every entry per the lib/ rules; do not bulk-skip on a hunch about the remainder.

## Prerequisites

- Obsidian CLI installed + configured (`Settings → General → Command line interface`)
- "Use [[Wikilinks]]" + "Automatically update internal links" enabled in Obsidian settings
- Always pass `vault="<name>"` before the subcommand (`obsidian vault="<name>" <command> ...`). It is a global option; after the subcommand it can be silently ignored, causing a wrong-vault write that still reports success.

## Sync-conflict exclusion

Treat Syncthing `.sync-conflict-YYYYMMDD-HHMMSS-DEVICEID` files as non-live artifacts, not notes. Do not index them, repair their links, rename them, include them in unresolved/orphan reports, or rewrite them during gardening. If audit/CLI output includes conflicts, filter them out before normal maintenance and triage them separately as sync-conflict merge/delete work.

## Pipeline

### Step 0: Locate vault + verify Obsidian running

```bash
cat ~/.config/obsidian-knowledge/vaults.yaml   # get VAULT path
cat "$VAULT/CLAUDE.md"                          # naming conventions
cat "$VAULT/.claude/obsidian-knowledge.yaml"    # zone config
obsidian version                                # verify running; launch if not
```

### Step 1: Read state

Read `$VAULT/Utility/obsidian-knowledge/needs-attention.md` — note known issues, detect resolved ones.

### Step 2: Run structural audit

```bash
SCRIPTS="${HERMES_VAULT_ORGANIZER_SCRIPTS:-$HOME/.hermes/skills/note-taking/vault-organizer}"
if [ ! -f "$SCRIPTS/vault-audit.py" ]; then
  SCRIPTS=$(dirname $(find ~/.claude/plugins ~/.hermes/skills -name "vault-audit.py" 2>/dev/null | head -1))
fi
python3 "$SCRIPTS/vault-audit.py" "$VAULT"
```

Output header tells you which lib/ file to read for each issue type. Fix every line.

### Step 3: Fix structural issues

**`MISSING_INDEX <folder>`** — create index.md. Read `lib/index-format.md`.

**`NOT_INDEXED <index> entry=<name>`** — add entry. Read `lib/index-format.md`.

**`DUMPING_GROUND <folder> misplaced=N inline_total=T subfolders=M`** — classify the misplaced inline files (date-prefixed and `*-design`/`-convo`/`-diary`), move them to typed subfolders. Read `lib/note-types.md` + `lib/index-format.md`.

**`STACKED_FRONTMATTER <file>`** — auto-fix stray duplicate `---` markers:

```bash
python3 "$SCRIPTS/fix-stacked-frontmatter.py" --fix <file1> <file2> ...
```

Files reported as `NEEDS_MERGE` (real second block with keys) require manual merge — read `lib/stacked-frontmatter.md`.

After structural fixes, rename ambiguous non-markdown files. Read `lib/rename-files.md`.

### Step 4: Detect + fix broken links

```bash
obsidian unresolved verbose format=json | python3 "$SCRIPTS/filter-unresolved-links.py" "$VAULT"
obsidian unresolved verbose format=json | python3 "$SCRIPTS/recover-unresolved-links.py" "$VAULT" > /tmp/vault-unresolved-recovery.tsv
obsidian orphans
```

Read `lib/broken-links.md` for triage rules on the surviving candidates. Use `recover-unresolved-links.py --apply` only after reviewing its report; it is designed to rewrite only unique exact/high-confidence filename recoveries and leave ambiguous/concept-stub cases untouched. Walk the full list — the filter/recovery scripts reduce risk and queue deterministic candidates, but the surviving remainder is still the work, not noise. Do not collapse the tail into a "mostly stubs, skip" bucket without checking each.

### Step 5: Convention violations sweep

Vault-wide check for the same patterns enforced at write-time by `enforce-conventions.py` and surfaced at session-start by `doctor.py`. Catches accumulated pre-existing violations the hooks couldn't have seen.

```bash
python3 "$SCRIPTS/convention-sweep.py" "$VAULT"
```

Output (tab-separated, one issue per line):

```
WIKILINK_EXT  <rel_path>:<line>  <match>     # [[foo.md]] → should be [[foo]]
UNDATED_FILE  <rel_path>                     # in Journal/diary/convos/plans without YYYY-MM-DD prefix
YAML_ERR      <rel_path>         <error>     # malformed frontmatter
```

For each issue: rename file (UNDATED_FILE) via `obsidian rename`, fix link (WIKILINK_EXT) by editing the file, fix YAML (YAML_ERR) by editing frontmatter. If unresolvable, add to needs-attention.md (read `lib/state-files.md` for format). Vault-organizer is the sole writer to needs-attention.md — hooks just enforce/surface.

### Step 6: Regenerate reports

Rewrite `$VAULT/Utility/obsidian-knowledge/reports/open-questions.md` from scratch:

```bash
python3 "$SCRIPTS/find-open-questions.py" "$VAULT"
```

Output is `<rel_path>\t<line>\t<question_text>` per hit. Code-block examples
are filtered automatically. Build one entry per line:
`- [[wiki/path/to/page]] — line N — "question text"`

Preserve existing file structure (heading, regeneration notice, scope section). Only entry list + `Last run:` timestamp change.

### Step 7: Update needs-attention.md

Remove resolved entries. Add new unresolvable issues. Read `lib/state-files.md` for format.

### Step 8: Create changelog entry

Create `$VAULT/Utility/obsidian-knowledge/changelog/YYYY-MM-DD-HHMMSS-<slug>.md`. Read `lib/state-files.md` for format. Do not edit a shared changelog index; per-session files are the concurrency-safe audit record. Skip if no actions taken.
