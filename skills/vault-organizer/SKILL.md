---
name: vault-organizer
description: >-
  This skill should be used when the user asks to "organize the vault",
  "update indexes", "fix broken links", "rename ambiguous files", "fix
  filenames", "garden the vault", "sync indexes", "clean up the vault",
  "maintain the vault", or after making substantial structural edits
  (creating, moving, renaming, or deleting files) in an Obsidian vault.
  Also triggered by scheduled cron invocations for routine vault maintenance.
version: 1.1.0
---

# Vault Organizer

Maintain Obsidian vault structure. Single-pass pipeline. Never edit primary file content — only indexes, links, locations, names.

**Don't read lib/ files upfront. Fetch them only when you hit that step.**

## Prerequisites

- Obsidian CLI installed + configured (`Settings → General → Command line interface`)
- "Use [[Wikilinks]]" + "Automatically update internal links" enabled in Obsidian settings
- Always pass `vault="<name>"` to every CLI call — default resolves to most recently focused vault, which may be wrong.

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
SCRIPT=$(find ~/.claude/plugins -name "vault-audit.py" 2>/dev/null | head -1)
python3 "$SCRIPT" "$VAULT"
```

Output header tells you which lib/ file to read for each issue type. Fix every line.

### Step 3: Fix structural issues

**`MISSING_INDEX <folder>`** — create index.md. Read `lib/index-format.md`.

**`MISSING_ENTRY <index> missing=<name>`** — add entry. Read `lib/index-format.md`.

**`DUMPING_GROUND <folder> inline=N subfolders=M`** — classify inline files, move to typed subfolders. Read `lib/note-types.md` + `lib/index-format.md`.

After structural fixes, rename ambiguous non-markdown files. Read `lib/rename-files.md`.

### Step 4: Detect + fix broken links

```bash
obsidian unresolved verbose format=json
obsidian orphans
```

Read `lib/broken-links.md` for filtering rules (most unresolved links are intentional stubs — don't act blindly).

### Step 5: Regenerate reports

Rewrite `$VAULT/Utility/obsidian-knowledge/reports/open-questions.md` from scratch:

```bash
grep -rn '^> \[!question\]' "$VAULT/wiki" --include='*.md' --exclude-dir=_sources
```

For each hit: read surrounding lines, strip `> ` prefix, build entry:
`- [[wiki/path/to/page]] — line N — "question text"`

Preserve existing file structure (heading, regeneration notice, scope section). Only entry list + `Last run:` timestamp change.

### Step 6: Update needs-attention.md

Remove resolved entries. Add new unresolvable issues. Read `lib/state-files.md` for format.

### Step 7: Append to changelog.md

Date-stamped entry at top of `$VAULT/Utility/obsidian-knowledge/changelog.md`. Read `lib/state-files.md` for format. Skip if no actions taken.
