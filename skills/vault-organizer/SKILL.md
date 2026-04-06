---
name: vault-organizer
description: >-
  This skill should be used when the user asks to "organize the vault",
  "update indexes", "fix broken links", "rename ambiguous files", "fix
  filenames", "garden the vault", "sync indexes", "clean up the vault",
  "maintain the vault", or after making substantial structural edits
  (creating, moving, renaming, or deleting files) in an Obsidian vault.
  Also triggered by scheduled cron invocations for routine vault maintenance.
version: 0.4.0
---

# Vault Organizer

Maintain an Obsidian vault's structural organization: sync indexes, organize
and rename files, detect and fix broken links, and report unresolvable issues.
This skill runs a single-pass pipeline that never edits the content of primary
files — only indexes, links, file locations, and file names.

## Prerequisites

- **Obsidian CLI** must be installed and configured
  (`Settings → General → Command line interface`)
- **"Use [[Wikilinks]]"** must be enabled in Obsidian settings
- **"Automatically update internal links"** must be enabled in Obsidian settings
- If more than one vault is registered in Obsidian, specify which vault to
  target in every CLI call (e.g., `obsidian vault="My Vault" ...`). The CLI
  defaults to the most recently focused vault, which may not be the one being
  organized.

## Note types

The plugin recognizes these note types. Use them to classify files during
organization and determine correct placement:

- **Source / reference** — original documents, scans, PDFs, images.
  Lives in a `_sources/` subfolder of the relevant area. Write-protected.
- **Wiki** — compiled knowledge about a topic. Lives inline in the
  relevant folder.
- **Guide** — prescriptive how-to procedures. Lives inline.
- **Design doc / plan** — decision records and implementation plans.
  Lives in a `plans/` subfolder of the relevant area.
- **Session note** — agent-generated output from a conversation session.
  Lives in a `sessions/` subfolder, with a suffix indicating the type:
  `-diary` for narrative accounts of processes, incidents, or events;
  `-convo` for analytical synthesis, comparisons, or decision rationales.
- **TODO** — task backlogs. Prefixed with context to avoid wikilink
  collisions (e.g., `TODO-project.md`).
- **Index** — folder navigation. See Step 4.

## State files

All persistent state lives in `<vault>/.config/obsidian-knowledge/`.
Create this directory on first run if it does not exist.

### CHANGELOG.md

Append-only log of actions taken. Newest entry first. Each run adds a
date-stamped section. Keep entries terse — one line per action. Link out
to session notes, diary entries, or guides for detail rather than
documenting inline.

Format:
```
# Changelog

## YYYY-MM-DD

- Created `folder/index.md` (N entries)
- Moved `old/path.md` → `new/path.md` via `obsidian move`
- Renamed `old/scan.pdf.pdf` → `2020-02-15-dispute-timesheet.pdf`
- Fixed N stale links found during move/rename sanity check
- Added `path/to/file.md:15` to NEEDS_ATTENTION — unresolved link, no match found
- Resolved `path/to/old-issue.md` from NEEDS_ATTENTION — renamed to `descriptive-name.md`
- See [[2026-04-06-vault-reorg-diary]] for details
```

### NEEDS_ATTENTION.md

Living worklist of issues requiring human judgment. Entries are `- [ ]`
checkboxes with file path, issue description, and any candidates considered.
Delete entries when resolved — do not check them off.

Format:
```
# Needs Attention

- [ ] `file.md:15` — unresolved link to `target.md`. Candidate: `other.md`
  covers similar topic but not confident it's the intended target
- [ ] `file.md:30` — unresolved link to `missing.md`, no matching file found
```

## Pipeline

Execute these steps in order each run.

### Step 0: Ensure Obsidian is running

Run `obsidian version`. If it fails, launch Obsidian (e.g., run `obsidian` or
open it via the system launcher) and retry `obsidian version` up to 3 times
with a few seconds between attempts. If Obsidian still cannot be reached,
log the failure to CHANGELOG and exit.

### Step 1: Read state

Read `NEEDS_ATTENTION.md` if it exists. Parse existing entries to:
- Avoid re-investigating known issues
- Detect items that have been resolved since last run (the referenced file or
  link now exists)

### Step 2: Scan structure

Walk the vault directory tree, skipping dotfolders (`.obsidian`, `.config`,
`.git`, `.trash`, etc.). Build a map of:
- All folders and which have an `index.md`
- All `.md` files and their locations
- All non-markdown files and their locations
- Parent-child folder relationships

### Step 3: Organize files

Respect the vault's access zones defined in `.claude/vault-zones.yaml`.
Only organize files in zones where the agent has write access.

For files clearly misplaced (in a parent folder when a more specific child
folder exists, or not matching their folder's topic scope):

When in doubt, do not move — only relocate a file when the correct
destination is unambiguous from folder naming alone.

1. Use `obsidian move path="old/path.md" to="new/folder"` to relocate files
   and `obsidian rename path="file.md" name="new-name"` for in-place renames.
   Never use raw filesystem `mv` or `rename`.
2. After each move, grep the vault for the old filename as a sanity check that
   all references were updated by Obsidian.
3. If any stale references are found during this check — whether markdown-style
   links `[text](path)`, raw unlinked path mentions (e.g., `See ../folder/file.md`),
   or wikilinks that did not update — convert them to proper wikilinks.

Do not do a standalone vault-wide scan for markdown links. Only fix link format
issues encountered opportunistically during move/rename sanity checks.

#### Rename ambiguous files

After organizing file locations, scan all non-markdown files found in Step 2 for
ambiguous names. A filename is considered ambiguous if it matches any of these
patterns:

1. **Device-generated** — matches patterns like `IMG_\d+`, `DSC_\d+`,
   `Screenshot \d+`, `Photograph (\d+)`, `PXL_\d+`
2. **Hash-based** — filename (minus extension) is entirely hex characters, or
   matches common hash+suffix patterns (e.g.,
   `db02eee9316b577e8f8a097b81ab6126-uncropped_scaled_within_1536_1152`)
3. **Generic labels** — filename (minus extension and any date prefix) is a
   single common word like `scan`, `receipt`, `invoice`, `document`, `form`,
   `image`, `photo`, `file`, `untitled`, or a numbered variant like `form 1`,
   `form 2`. This list is illustrative — flag any filename that provides no
   meaningful identification of the file's content.
4. **Numeric-only** — filename (minus extension) is purely digits (e.g.,
   `15863.gif`)
5. **Double extensions** — like `scan.pdf.pdf` (also fix the extension)

**Scope:** Include all vault folders including `_sources/` directories
(use the `I_AM_BEING_CAREFUL=1` escape hatch for renames there). Skip
`.trash/` and dotfolders. Skip files that already have descriptive,
human-readable names.

For each flagged file:

**1. Read the file** to extract identifying information:
- **PDFs:** Read text content. Look for dates, vendor names, order/reference
  IDs, document type.
- **Images (jpg, png, webp, gif):** View the image using multimodal
  capabilities. Identify what is depicted — a document, receipt, room photo,
  ID card, etc.
- **Other formats:** Best-effort read. If the format is not readable, rely on
  folder context alone.

**2. Fix image orientation.** If the file is an image and it is not right-side-up
(detected via EXIF orientation tag or visual inspection), rotate it to the
correct orientation before renaming. Use `exiftool -auto-rotate` or
`magick mogrify -auto-orient` to apply the correction. For files in
`_sources/`, do not modify — add to NEEDS_ATTENTION noting the orientation
issue so the user can decide whether to rotate the original.

**3. Gather context:**
- **Folder path** — strong signal (e.g., a `taxes/2015/` parent implies
  a 2015 tax document). Used as a hint, not ground truth.
- **Neighboring files** — if siblings are well-named, they hint at what this
  file is.
- **EXIF data** — for images, if `exiftool` is available. Contains dates,
  camera info.

The file's own content is the ultimate source of truth. If folder context
conflicts with file content, trust file content.

**4. Generate a new name** following the vault's naming conventions in
CLAUDE.md. Date source priority:
1. File content (extracted date from text/document)
2. EXIF metadata
3. Filename-embedded date (e.g., `IMG_20160130` → `2016-01-30`)
4. Folder context (e.g., parent folder named `2015/`)
5. Omit date

**5. Assign confidence and act:**

- **High confidence** — clear text extraction with unambiguous date, vendor,
  or description; or image content clearly matches and confirms folder context.
  Rename via `obsidian rename path="old/name.ext" name="new-name.ext"`. For
  files in `_sources/`, use the `I_AM_BEING_CAREFUL=1` escape hatch. Then
  grep the vault for the old filename to verify Obsidian updated all
  references — fix any stale wikilinks, markdown links, or raw path mentions.
- **Low confidence** — vague image content, no date found, folder context is
  the primary signal, or multiple plausible interpretations. Add to
  NEEDS_ATTENTION with the proposed name (see format below).

NEEDS_ATTENTION entry format for rename escalations:
```
- [ ] `path/to/IMG_20161222_124409.jpg` — ambiguous filename.
  Proposed: `2016-12-22-fl-drivers-license-photo.jpg`.
  Confidence low: name derived primarily from folder context, image shows
  a card but details unclear.
```

### Step 4: Sync indexes

For every folder in the `ai_managed` zones (per `.claude/vault-zones.yaml`):

**If no `index.md` exists:** Create one with a heading matching the folder name
and thin pointer entries for each file and subfolder.

**If `index.md` exists:** Add entries for files/subfolders not yet listed.
Remove entries pointing to files that no longer exist. Preserve any existing
entries that are still valid.

#### Index entry format

```markdown
# Folder Name

- [[subfolder/index|Subfolder Display Name]] — orientation phrase
- [[some-file]] — orientation phrase
```

Rules:
- One entry per line: wikilink + em dash + short orientation phrase
- The phrase answers "what is this?" — enough to decide whether to open the
  file. Not a summary. Not a sentence.
- Subfolders first (linking to their `index.md` with display alias), then
  files alphabetically
- Disambiguate duplicate `index.md` names with relative path:
  `[[systems/index]]` not `[[index]]`
- No frontmatter, no properties, no metadata on the index itself
- The heading is the only non-list content in the file

### Step 5: Detect and fix broken links

Run `obsidian unresolved verbose format=json` to get all unresolved links
with their source files.

For each unresolved link, apply this resolution logic in order:

1. **Exact name match:** Search the vault for a file with the same name. If
   found (it was moved), fix the link to point to the new location.
2. **Similar match:** Search for files with similar names or overlapping
   content. If one is a clear match with high confidence, fix the link.
3. **Ambiguous candidate:** If a plausible candidate exists but confidence is
   low, add to NEEDS_ATTENTION with the candidate noted.
4. **No match:** If nothing resembles the target, add to NEEDS_ATTENTION with
   no candidate.

Also run:
- `obsidian orphans` — files with no incoming links. For orphans in
  `ai_managed` zones, add them to their parent folder's index if not
  already present. Ignore orphans outside managed zones.
- `obsidian deadends` — files with no outgoing links. Informational only;
  many leaf files legitimately have no outgoing links. Do not flag these.

### Step 6: Update NEEDS_ATTENTION.md

Remove entries for issues resolved during this run. Add new entries for
unresolvable issues found. Write the file (or delete it if empty).

### Step 7: Append to CHANGELOG.md

Add a date-stamped section at the top summarizing all actions taken: files
moved, indexes created/updated, links fixed, NEEDS_ATTENTION items
added/resolved. Skip the entry entirely if no actions were taken.
