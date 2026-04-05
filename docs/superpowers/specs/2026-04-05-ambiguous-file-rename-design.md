# Ambiguous File Rename — Design Spec

**Date:** 2026-04-05
**Status:** Approved
**Skill:** vault-organizer

## Problem

The vault contains ~58+ non-markdown files with ambiguous names: device-generated
(`IMG_20160130_145015.jpg`), hash-based (`db02eee9316b577e8f8a097b81ab6126-uncropped_scaled_within_1536_1152.webp`),
generic labels (`scan.pdf`, `form 1.pdf`), numeric-only (`15863.gif`), and double
extensions (`scan.pdf.pdf`). These names provide no context about file content and
make vault navigation harder.

## Solution

Extend Step 3 (Organize Files) of the vault-organizer skill to detect ambiguously-named
non-markdown files, read them, generate descriptive names, and rename them using the
vault's existing naming convention.

## Naming Convention

- **With date:** `yyyy-mm-dd-descriptive-slug.ext`
- **Without date:** `descriptive-slug.ext`

Slug is lowercase, hyphen-separated, human-readable. Date source priority:

1. File content (extracted date from text/document)
2. EXIF metadata
3. Filename-embedded date (e.g., `IMG_20160130` → `2016-01-30`)
4. Folder context (e.g., parent folder named `2015/`)
5. Omit date

## Detection Heuristics

A non-markdown file is flagged as ambiguously named if its filename matches any of:

1. **Device-generated** — patterns like `IMG_\d+`, `DSC_\d+`, `Screenshot \d+`,
   `Photograph (\d+)`, `PXL_\d+`
2. **Hash-based** — filename (minus extension) is entirely hex characters, or matches
   common hash+suffix patterns
3. **Generic labels** — filename (minus extension and any date prefix) is a single
   common word: `scan`, `receipt`, `invoice`, `document`, `form`, `image`, `photo`,
   `file`, `untitled`, `new file`, or a numbered variant like `form 1`, `form 2`.
   This list is illustrative, not exhaustive — the agent should flag any filename
   that provides no meaningful identification of the file's content.
4. **Numeric-only** — filename (minus extension) is purely digits
5. **Double extensions** — like `scan.pdf.pdf`

### Scope

- **Included:** All vault folders, including `_sources/` directories
- **Skipped:** `.trash/`, dotfolders (`.obsidian`, `.config`, `.git`, etc.)
- **Skipped:** Files already following `YYYY-MM-DD-descriptive-slug` convention

## Name Generation

For each flagged file:

### 1. Read the file

- **PDFs:** Extract text content. Look for dates, vendor names, order/reference IDs,
  document type.
- **Images (jpg, png, webp, gif):** View the image using multimodal capabilities.
  Identify what's depicted — a document, receipt, photo of a room, ID card, etc.
- **Other files:** Best-effort read. If the format isn't readable, rely on folder
  context alone.

### 2. Fix image orientation

If the file is an image and it is not right-side-up (detected via EXIF orientation
tag or visual inspection), rotate it to the correct orientation before renaming.
Use a tool like `exiftool` to apply EXIF orientation, or `convert`/`magick` for
physical rotation if needed.

### 3. Gather context

- **Folder path** — strong signal (e.g., `life/finance-property/taxes/2015/` implies
  a 2015 tax document). Used as a hint, not as ground truth.
- **Neighboring files** — if siblings are well-named, they hint at what this file is.
- **EXIF data** — for images, if `exiftool` is available. Contains dates, camera info.

The file's own content is the ultimate source of truth. If folder context conflicts
with file content, trust file content.

### 4. Generate name

Produce a `yyyy-mm-dd-descriptive-slug.ext` name (or `descriptive-slug.ext` if no
date). The slug should be specific enough to identify the file without opening it.

### 5. Assign confidence

- **High confidence:** Clear text extraction with unambiguous date, vendor, or
  description. Or image content clearly matches folder context. Auto-rename.
- **Low confidence:** Vague image content, no date found, folder context is the
  primary signal, or multiple plausible interpretations. Escalate to NEEDS_ATTENTION.

## Rename Execution

High-confidence renames:

1. Rename via `obsidian rename path="old/name.ext" name="new-name.ext"` — never raw
   filesystem commands.
2. Sanity-check — grep the vault for the old filename to verify Obsidian updated all
   references. Fix any stale wikilinks, markdown links, or raw path mentions found.
3. For files in `_sources/`, use the `I_AM_BEING_CAREFUL=1` escape hatch since the
   PreToolUse hook blocks writes to those paths.

Low-confidence escalations go to `NEEDS_ATTENTION.md`:

```
- [ ] `life/vital-docs/ids/IMG_20161222_124409.jpg` — ambiguous filename.
  Proposed: `2016-12-22-fl-drivers-license-photo.jpg`.
  Confidence low: name derived primarily from folder context, image shows a card
  but details unclear.
```

## Logging

Each rename or escalation is logged to `CHANGELOG.md`:

```
- Renamed `old/scan.pdf.pdf` → `2020-02-15-fairwork-dispute-timesheet.pdf` (high confidence)
- Flagged `old/IMG_20161222_124409.jpg` — proposed: `2016-12-22-fl-drivers-license-photo.jpg` (low confidence, added to NEEDS_ATTENTION)
- Rotated `old/IMG_20161222_124409.jpg` to correct orientation
```

## Related Cleanup

### Rename hook script

Rename `hooks/remind-log.sh` → `hooks/update-changelog.sh`. Update the script to
reference `CHANGELOG.md` instead of `log.md`.

### Rename vault log file

Rename the vault's `log.md` → `CHANGELOG.md` to match the skill's convention.

## Integration with Existing Pipeline

This feature is added to the existing Step 3 (Organize Files) of the vault-organizer
skill. It runs as a sub-step after the existing file-move logic:

1. *(existing)* Move misplaced files to correct folders
2. *(new)* Detect ambiguously-named files
3. *(new)* For each flagged file: read content, fix orientation if needed, generate
   name, assign confidence
4. *(new)* High confidence: auto-rename + sanity-check links
5. *(new)* Low confidence: escalate to NEEDS_ATTENTION with proposed name
6. *(existing)* Post-rename sanity checks and link fixes

The rest of the pipeline (Steps 4-7) runs unchanged afterward.
