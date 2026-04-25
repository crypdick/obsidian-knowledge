---
name: vault-organizer
description: >-
  This skill should be used when the user asks to "organize the vault",
  "update indexes", "fix broken links", "rename ambiguous files", "fix
  filenames", "garden the vault", "sync indexes", "clean up the vault",
  "maintain the vault", or after making substantial structural edits
  (creating, moving, renaming, or deleting files) in an Obsidian vault.
  Also triggered by scheduled cron invocations for routine vault maintenance.
version: 0.9.0
---

# Vault Organizer

Maintain Obsidian vault structure: sync indexes, organize/rename files, detect/fix broken links, report unresolvable issues. Single-pass pipeline. Never edit primary file content — only indexes, links, locations, names.

## Prerequisites

- **Obsidian CLI** installed + configured
  (`Settings → General → Command line interface`)
- **"Use [[Wikilinks]]"** enabled in Obsidian settings
- **"Automatically update internal links"** enabled in Obsidian settings
- Multiple vaults registered → specify target vault in every CLI call (e.g., `obsidian vault="My Vault" ...`). CLI defaults to most recently focused vault — may not match target.

## Orientation: vault root, state, and config locations

**Plugin may run from working directory that is NOT vault.** Locate vault first:

```bash
cat ~/.config/obsidian-knowledge/vaults.yaml
```

File lists vault root path(s). Use first vault unless user says else. All paths below relative to `<vault_root>`.

Key locations (relative to `<vault_root>`):
- **State files** — `<vault_root>/Utility/obsidian-knowledge/` (changelog.md, needs-attention.md)
- **Zone config** — `<vault_root>/.claude/obsidian-knowledge.yaml`
- **Vault instructions** — `<vault_root>/CLAUDE.md` (naming conventions, agent rules)

At vault root, not inside managed sub-zone — even if working dir elsewhere.

## Note types

Plugin recognizes these. Use to classify + place files:

- **Source / reference** — original docs, scans, PDFs, images. Lives in `_sources/` subfolder of relevant area. Write-protected.
- **Wiki** — compiled knowledge on topic. Inline in folder.
- **Guide** — prescriptive how-to. Inline.
- **Design doc / plan** — decision records, implementation plans. `plans/` subfolder.
- **Convo note** — agent synthesis from conversation: comparisons, decision rationales, research summaries, discoveries. `convos/` subfolder.
- **Diary note** — narrative of process, incident, event. `diary/` subfolder.
- **TODO** — task backlogs. Prefix with context to avoid wikilink collision (e.g., `TODO-project.md`).
- **Index** — folder navigation. See Step 4.

## State files

Persistent state in `<vault_root>/Utility/obsidian-knowledge/`. Create dir on first run if missing.

### changelog.md

Append-only log. Newest first. Each run adds date-stamped section. One line per action. Link out to session notes, diary, guides — don't document inline.

Format:
```
# Changelog

## YYYY-MM-DD

- Created `folder/index.md` (N entries)
- Moved `old/path.md` → `new/path.md` via `obsidian move`
- Renamed `old/scan.pdf.pdf` → `2020-02-15-dispute-timesheet.pdf`
- Fixed N stale links found during move/rename sanity check
- Added `path/to/file.md:15` to needs-attention.md — unresolved link, no match found
- Resolved `path/to/old-issue.md` from needs-attention.md — renamed to `descriptive-name.md`
- See [[2026-04-06-vault-reorg-diary]] for details
```

### needs-attention.md

Living worklist for human judgment. Entries `- [ ]` checkboxes with path, issue, candidates. Delete when resolved — don't check off.

Format:
```
# Needs Attention

- [ ] `file.md:15` — unresolved link to `target.md`. Candidate: `other.md`
  covers similar topic but not confident it's the intended target
- [ ] `file.md:30` — unresolved link to `missing.md`, no matching file found
```

## Pipeline

Run steps in order each run.

### Step 0: Locate vault and ensure Obsidian is running

**Find vault root first:**
```bash
cat ~/.config/obsidian-knowledge/vaults.yaml
```

Set `VAULT` to path from file (e.g., `/home/user/Documents/obsidian`). Then read vault instructions + zone config:
```bash
cat "$VAULT/CLAUDE.md"          # naming conventions, agent rules
cat "$VAULT/.claude/obsidian-knowledge.yaml"  # ai_managed, ai_assisted, read-only zones
```

**Verify Obsidian running:**
Run `obsidian version`. Fail → launch Obsidian (run `obsidian` or system launcher), retry `obsidian version` up to 3 times, few seconds between. Still unreachable → log to changelog.md, exit.

### Step 1: Read state

Read `$VAULT/Utility/obsidian-knowledge/needs-attention.md` if exists. Parse entries to:
- Skip known issues
- Detect items resolved since last run (referenced file/link now exists)

### Step 2: Scan structure

Walk vault tree, skip dotfolders (`.obsidian`, `.config`, `.git`, `.trash`, etc.). Build map:
- All folders + which have `index.md`
- All `.md` files + locations
- All non-markdown files + locations
- Parent-child folder relationships

**Find folders missing indexes** (within managed zone, e.g., `wiki/`):
```bash
find "$VAULT/wiki" -type d | grep -v '/\.' | sort | while read dir; do
  [ ! -f "$dir/index.md" ] && echo "MISSING: $dir"
done
```

Shows folders needing indexes — run before other analysis to scope work.

### Step 3: Organize files

Respect zones in `$VAULT/.claude/obsidian-knowledge.yaml`. Only organize files in zones with write access.

For files clearly misplaced (parent folder when more specific child exists, or topic mismatch):

When in doubt, don't move — only relocate when correct destination unambiguous from folder naming alone.

1. Use `obsidian move path="old/path.md" to="new/folder"` to relocate, `obsidian rename path="file.md" name="new-name"` for in-place rename. Never raw filesystem `mv` or `rename`.
2. After move, grep vault for old filename — sanity check Obsidian updated all refs.
3. Stale refs found during check — markdown links `[text](path)`, raw path mentions (e.g., `See ../folder/file.md`), wikilinks that didn't update — convert to proper wikilinks.

No standalone vault-wide markdown link scan. Only fix link format issues found opportunistically during move/rename sanity checks.

#### Rename ambiguous files

After organizing locations, scan all non-markdown files from Step 2 for ambiguous names. Ambiguous if matches:

1. **Device-generated** — patterns like `IMG_\d+`, `DSC_\d+`, `Screenshot \d+`, `Photograph (\d+)`, `PXL_\d+`
2. **Hash-based** — filename (minus ext) entirely hex, or hash+suffix patterns (e.g., `db02eee9316b577e8f8a097b81ab6126-uncropped_scaled_within_1536_1152`)
3. **Generic labels** — filename (minus ext + date prefix) is single common word: `scan`, `receipt`, `invoice`, `document`, `form`, `image`, `photo`, `file`, `untitled`, or numbered variant (`form 1`, `form 2`). Illustrative — flag any name giving no meaningful ID of content.
4. **Numeric-only** — filename (minus ext) pure digits (e.g., `15863.gif`)
5. **Double extensions** — like `scan.pdf.pdf` (also fix ext)

**Scope:** All vault folders including `_sources/` (use `I_AM_BEING_CAREFUL=1` escape hatch for renames there). Skip `.trash/` + dotfolders. Skip files with descriptive human-readable names already.

For each flagged file:

**1. Read file** to extract identifying info:
- **PDFs:** Read text. Look for dates, vendors, order/reference IDs, doc type.
- **Images (jpg, png, webp, gif):** View via multimodal. Identify what depicted — document, receipt, room photo, ID card, etc.
- **Other formats:** Best-effort read. Unreadable → rely on folder context alone.

**2. Fix image orientation.** Image not right-side-up (EXIF orientation tag or visual) → rotate before rename. Use `exiftool -auto-rotate` or `magick mogrify -auto-orient`. Files in `_sources/` — don't modify, add to needs-attention.md noting orientation so user decides.

**3. Gather context:**
- **Folder path** — strong signal (e.g., `taxes/2015/` parent → 2015 tax doc). Hint, not ground truth.
- **Neighboring files** — well-named siblings hint at file identity.
- **EXIF data** — for images if `exiftool` available. Dates, camera info.

File content = ultimate truth. Folder context conflicts with file content → trust file content.

**4. Generate new name** per vault naming conventions in CLAUDE.md. Date source priority:
1. File content (extracted date)
2. EXIF metadata
3. Filename-embedded date (e.g., `IMG_20160130` → `2016-01-30`)
4. Folder context (parent folder named `2015/`)
5. Omit date

**5. Assign confidence + act:**

- **High confidence** — clear text extract with unambiguous date/vendor/desc, or image content matches + confirms folder. Rename via `obsidian rename path="old/name.ext" name="new-name.ext"`. Files in `_sources/` → use `I_AM_BEING_CAREFUL=1` escape hatch. Then grep vault for old filename — verify Obsidian updated refs. Fix any stale wikilinks, markdown links, raw path mentions.
- **Low confidence** — vague image, no date, folder context primary signal, or multiple plausible interpretations. Add to needs-attention.md with proposed name (format below).

needs-attention.md entry format for rename escalations:
```
- [ ] `path/to/IMG_20161222_124409.jpg` — ambiguous filename.
  Proposed: `2016-12-22-fl-drivers-license-photo.jpg`.
  Confidence low: name derived primarily from folder context, image shows
  a card but details unclear.
```

### Step 4: Sync indexes

For every folder in `ai_managed` zones (per `$VAULT/.claude/obsidian-knowledge.yaml`):

**No `index.md` exists:** Create with heading matching folder name + thin pointer entries for each file/subfolder.

**`index.md` exists:** Add entries for files/subfolders not listed. Remove entries pointing to nonexistent files. Preserve valid entries.

**Note on path-based wikilinks:** Updating existing indexes — watch for path-based wikilinks with outdated paths (e.g., `[[old/path/file|Display]]`). Show as broken in `obsidian unresolved`, cause files to show orphan even when listed. Replace stale path-based links with filename-based wikilinks (`[[filename|Display]]`) — Obsidian resolves reliably regardless of file location.

#### Index entry format

```markdown
# Folder Name

- [[subfolder/index|Subfolder Display Name]] — orientation phrase
- [[some-file]] — orientation phrase
```

Rules:
- One entry per line: wikilink + em dash + short orientation phrase
- Phrase answers "what is this?" — enough to decide open/skip. Not summary. Not sentence.
- Subfolders first (link to `index.md` with display alias), then files alphabetically
- Disambiguate duplicate `index.md` names with relative path: `[[systems/index]]` not `[[index]]`
- No frontmatter, no properties, no metadata on index itself
- Heading = only non-list content in file

### Step 5: Detect and fix broken links

Run `obsidian unresolved verbose format=json` for unresolved links + sources.

**Filter intentional stubs before investigating.** `obsidian unresolved` output almost always noisy — most entries deliberate forward references user never intended to create yet. Blindly acting → busy work + false positives.

Before investigating, narrow list:
- **Scope to managed zones.** Ignore links from files outside `ai_managed` zones — out of scope.
- **Recognise intentional stubs by naming convention.** Every vault has consistent link-naming patterns (prefixes, suffixes, brackets, sigils) marking "I'll write this note someday" vs real broken links. Scan raw output for recurring patterns — links appearing many times across unrelated files = stub convention, not mass breakage.
- **Template placeholders** (`{{...}}`, `<% ... %>`, similar) never actionable — skip.

Focus investigation on links **from files inside managed zones** referencing filenames expected to exist: structural files (`CLAUDE.md`, sibling indexes, guides), files referenced in prose as if existing, or links appearing once or twice not matching recurring patterns.

For each unresolved link worth investigating, apply:

1. **Exact name match:** Search vault for same-name file. Found (was moved) → fix link to new location.
2. **Similar match:** Search files with similar names or overlapping content. Clear high-confidence match → fix link.
3. **Ambiguous candidate:** Plausible candidate but low confidence → add to needs-attention.md with candidate noted.
4. **No match:** Nothing resembles target → add to needs-attention.md, no candidate.

Also run:
- `obsidian orphans` — files with no incoming links. Orphans in `ai_managed` zones → add to parent folder index if missing. Ignore orphans outside managed zones.
- `obsidian deadends` — files with no outgoing links. Informational only — many leaf files legitimately have none. Don't flag.

### Step 6: Regenerate reports

Rewrite content-health reports under `$VAULT/Utility/obsidian-knowledge/reports/`. Pure derivative zone — every file in `reports/` overwritten from scratch each run, nothing human-touched lives there.

One report currently:

**`open-questions.md`** — compiled list of `> [!question]` Obsidian callouts across `wiki/`. Agents + humans read to see unresolved questions flagged in prose.

Procedure:

1. Scan for callouts:
   ```bash
   grep -rn '^> \[!question\]' "$VAULT/wiki" --include='*.md' --exclude-dir=_sources
   ```
   Each match: `<file>:<line>:> [!question]`. Question text on next line(s), prefixed `> `. Multi-line questions continue until blank line or non-`>` line.

2. For each hit, read file around match to capture question body. Strip `> ` prefix from continuation lines, join with spaces. Collapse to single-line summary for report entry (full text stays in source).

3. Build entries, sorted by file path then line number:
   ```
   - [[wiki/relative/path/to/page]] — line N — "the question text"
   ```

4. Overwrite `$VAULT/Utility/obsidian-knowledge/reports/open-questions.md` with:
   - `# Open questions` heading
   - Regeneration notice (don't hand-edit)
   - `**Last run:** YYYY-MM-DD HH:MM` timestamp
   - Entry list — or `_No open questions flagged._` if zero hits
   - Marker convention reminder (verbatim from existing scaffold)
   - Scope section (verbatim from existing scaffold)

Live vault scaffold already has non-entry sections — preserve structure when regenerating. Only entry list + `Last run` line change between runs.

### Step 7: Update needs-attention.md

Remove entries for resolved issues. Add entries for unresolvable issues found. Write file (or delete if empty).

### Step 8: Append to changelog.md

Add date-stamped section at top of `$VAULT/Utility/obsidian-knowledge/changelog.md` summarizing actions: moves, indexes created/updated, links fixed, needs-attention.md items added/resolved, reports regenerated. Skip entry entirely if no actions taken.