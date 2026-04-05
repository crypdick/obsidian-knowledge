# Ambiguous File Rename — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the vault-organizer skill to detect and rename ambiguously-named non-markdown files using content analysis and folder context.

**Architecture:** Add a "rename ambiguous files" sub-step to Step 3 (Organize Files) in SKILL.md. Update the scan in Step 2 to include non-markdown files. Rename the Stop hook script from `remind-log.sh` to `update-changelog.sh` and update references. Bump plugin version.

**Tech Stack:** Markdown skill definition (SKILL.md), bash hook script, JSON plugin manifest

**Spec:** `docs/superpowers/specs/2026-04-05-ambiguous-file-rename-design.md`

---

### Task 1: Update Step 2 (Scan Structure) to include non-markdown files

**Files:**
- Modify: `skills/vault-organizer/SKILL.md:87-93`

- [ ] **Step 1: Edit the Step 2 scan scope**

In `skills/vault-organizer/SKILL.md`, replace lines 87-93:

```markdown
### Step 2: Scan structure

Walk the vault directory tree, skipping dotfolders (`.obsidian`, `.config`,
`.git`, `.trash`, etc.). Build a map of:
- All folders and which have an `index.md`
- All `.md` files and their locations
- Parent-child folder relationships
```

with:

```markdown
### Step 2: Scan structure

Walk the vault directory tree, skipping dotfolders (`.obsidian`, `.config`,
`.git`, `.trash`, etc.). Build a map of:
- All folders and which have an `index.md`
- All `.md` files and their locations
- All non-markdown files and their locations
- Parent-child folder relationships
```

- [ ] **Step 2: Commit**

```bash
cd /home/ricardo/src/PERSONAL/obsidian-knowledge-base-skill
git add skills/vault-organizer/SKILL.md
git commit -m "feat(vault-organizer): include non-markdown files in Step 2 scan"
```

---

### Task 2: Add ambiguous name detection and rename sub-step to Step 3

**Files:**
- Modify: `skills/vault-organizer/SKILL.md:95-113`

This is the core feature. We extend the existing Step 3 by appending a new sub-step
after the current file-move logic (lines 95-113).

- [ ] **Step 1: Add the rename sub-step after existing Step 3 content**

In `skills/vault-organizer/SKILL.md`, after line 113 (the last line of the current
Step 3, ending with "...during move/rename sanity checks."), insert the following:

```markdown

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

**Scope:** Include all vault folders including `_sources/` directories. Skip
`.trash/` and dotfolders. Skip files already following the
`YYYY-MM-DD-descriptive-slug` convention.

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
`magick mogrify -auto-orient` to apply the correction. For files in `_sources/`,
use the `I_AM_BEING_CAREFUL=1` escape hatch.

**3. Gather context:**
- **Folder path** — strong signal (e.g., `life/finance-property/taxes/2015/`
  implies a 2015 tax document). Used as a hint, not ground truth.
- **Neighboring files** — if siblings are well-named, they hint at what this
  file is.
- **EXIF data** — for images, if `exiftool` is available. Contains dates,
  camera info.

The file's own content is the ultimate source of truth. If folder context
conflicts with file content, trust file content.

**4. Generate a new name** following the vault convention:
- With date: `yyyy-mm-dd-descriptive-slug.ext`
- Without date: `descriptive-slug.ext`

Slug is lowercase, hyphen-separated, human-readable. Date source priority:
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
```

- [ ] **Step 2: Commit**

```bash
cd /home/ricardo/src/PERSONAL/obsidian-knowledge-base-skill
git add skills/vault-organizer/SKILL.md
git commit -m "feat(vault-organizer): add ambiguous file rename sub-step to Step 3"
```

---

### Task 3: Update CHANGELOG format to include rename entries

**Files:**
- Modify: `skills/vault-organizer/SKILL.md:36-52`

- [ ] **Step 1: Add rename log entry examples to the CHANGELOG format**

In `skills/vault-organizer/SKILL.md`, replace lines 42-52:

```markdown
```
# Changelog

## YYYY-MM-DD

- Created `folder/index.md` (N entries)
- Moved `old/path.md` → `new/path.md` via `obsidian move`
- Fixed N stale links found during move sanity check
- Added N items to NEEDS_ATTENTION
- Resolved N items from NEEDS_ATTENTION
```
```

with:

```markdown
```
# Changelog

## YYYY-MM-DD

- Created `folder/index.md` (N entries)
- Moved `old/path.md` → `new/path.md` via `obsidian move`
- Renamed `old/scan.pdf.pdf` → `2020-02-15-dispute-timesheet.pdf` (high confidence)
- Rotated `path/to/image.jpg` to correct orientation
- Flagged `path/to/IMG_123.jpg` — proposed: `2016-12-22-description.jpg` (low confidence, added to NEEDS_ATTENTION)
- Fixed N stale links found during move/rename sanity check
- Added N items to NEEDS_ATTENTION
- Resolved N items from NEEDS_ATTENTION
```
```

- [ ] **Step 2: Commit**

```bash
cd /home/ricardo/src/PERSONAL/obsidian-knowledge-base-skill
git add skills/vault-organizer/SKILL.md
git commit -m "feat(vault-organizer): add rename entries to CHANGELOG format"
```

---

### Task 4: Update skill description and intro

**Files:**
- Modify: `skills/vault-organizer/SKILL.md:1-18`

- [ ] **Step 1: Update the skill description to mention file renaming**

In `skills/vault-organizer/SKILL.md`, replace the frontmatter description (lines 3-9):

```yaml
description: >-
  This skill should be used when the user asks to "organize the vault",
  "update indexes", "fix broken links", "garden the vault", "sync indexes",
  "clean up the vault", "maintain the vault", or after making substantial
  structural edits (creating, moving, renaming, or deleting files) in an
  Obsidian vault. Also triggered by scheduled cron invocations for routine
  vault maintenance.
```

with:

```yaml
description: >-
  This skill should be used when the user asks to "organize the vault",
  "update indexes", "fix broken links", "rename ambiguous files", "fix
  filenames", "garden the vault", "sync indexes", "clean up the vault",
  "maintain the vault", or after making substantial structural edits
  (creating, moving, renaming, or deleting files) in an Obsidian vault.
  Also triggered by scheduled cron invocations for routine vault maintenance.
```

- [ ] **Step 2: Update the intro paragraph**

Replace lines 15-18:

```markdown
Maintain an Obsidian vault's structural organization: sync indexes, organize
files, detect and fix broken links, and report unresolvable issues. This skill
runs a single-pass pipeline that never edits the content of primary files —
only indexes, links, and file locations.
```

with:

```markdown
Maintain an Obsidian vault's structural organization: sync indexes, organize
and rename files, detect and fix broken links, and report unresolvable issues.
This skill runs a single-pass pipeline that never edits the content of primary
files — only indexes, links, file locations, and file names.
```

- [ ] **Step 3: Commit**

```bash
cd /home/ricardo/src/PERSONAL/obsidian-knowledge-base-skill
git add skills/vault-organizer/SKILL.md
git commit -m "feat(vault-organizer): update skill description to mention file renaming"
```

---

### Task 5: Rename hook script and update references

**Files:**
- Rename: `hooks/remind-log.sh` → `hooks/update-changelog.sh`
- Modify: `hooks/update-changelog.sh` (content update)
- Modify: `.claude-plugin/plugin.json:17`

- [ ] **Step 1: Rename the hook script**

```bash
cd /home/ricardo/src/PERSONAL/obsidian-knowledge-base-skill
git mv hooks/remind-log.sh hooks/update-changelog.sh
```

- [ ] **Step 2: Update the hook script content**

Replace the full content of `hooks/update-changelog.sh` with:

```bash
#!/usr/bin/env bash
# Stop hook: remind the agent to update CHANGELOG.md in the vault.
# Only fires when working inside an Obsidian vault directory.
[[ "$PWD" == *obsidian* ]] || exit 0

cat <<'EOF'
{
  "decision": "block",
  "reason": "Reminder: if this session produced anything valuable for future agents to know (edits, decisions, discoveries, context, dead ends), append a dated entry to CHANGELOG.md. If nothing substantive happened or you already logged, carry on."
}
EOF
```

- [ ] **Step 3: Update plugin.json hook reference**

In `.claude-plugin/plugin.json`, replace line 17:

```json
            "command": "bash ${CLAUDE_PLUGIN_ROOT}/hooks/remind-log.sh"
```

with:

```json
            "command": "bash ${CLAUDE_PLUGIN_ROOT}/hooks/update-changelog.sh"
```

- [ ] **Step 4: Commit**

```bash
cd /home/ricardo/src/PERSONAL/obsidian-knowledge-base-skill
git add hooks/update-changelog.sh .claude-plugin/plugin.json
git commit -m "refactor: rename remind-log.sh to update-changelog.sh, reference CHANGELOG.md"
```

---

### Task 6: Bump plugin version

**Files:**
- Modify: `.claude-plugin/plugin.json:3`
- Modify: `.claude-plugin/marketplace.json:13`
- Modify: `skills/vault-organizer/SKILL.md:10`

- [ ] **Step 1: Bump version in plugin.json**

In `.claude-plugin/plugin.json`, replace line 3:

```json
  "version": "0.2.0",
```

with:

```json
  "version": "0.3.0",
```

- [ ] **Step 2: Bump version in marketplace.json**

In `.claude-plugin/marketplace.json`, replace line 13:

```json
      "version": "0.2.0"
```

with:

```json
      "version": "0.3.0"
```

- [ ] **Step 3: Bump version in SKILL.md**

In `skills/vault-organizer/SKILL.md`, replace line 10:

```yaml
version: 0.1.0
```

with:

```yaml
version: 0.2.0
```

- [ ] **Step 4: Commit**

```bash
cd /home/ricardo/src/PERSONAL/obsidian-knowledge-base-skill
git add .claude-plugin/plugin.json .claude-plugin/marketplace.json skills/vault-organizer/SKILL.md
git commit -m "chore: bump plugin version to 0.3.0, skill version to 0.2.0"
```
