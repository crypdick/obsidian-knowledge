# Rename ambiguous files

Reference for renaming non-markdown files with ambiguous names.

## What counts as ambiguous

1. **Device-generated** — `IMG_\d+`, `DSC_\d+`, `Screenshot \d+`, `Photograph (\d+)`, `PXL_\d+`
2. **Hash-based** — filename (minus ext) entirely hex, or hash+suffix patterns
3. **Generic labels** — filename (minus ext + date prefix) is a single common word: `scan`, `receipt`, `invoice`, `document`, `form`, `image`, `photo`, `file`, `untitled`, or numbered variant. Flag any name giving no meaningful ID of content.
4. **Numeric-only** — filename (minus ext) pure digits (e.g., `15863.gif`)
5. **Double extensions** — like `scan.pdf.pdf` (also fix ext)

**Scope:** All vault folders including `_sources/` (use `I_AM_BEING_CAREFUL=1` escape hatch for renames there). Skip `.trash/` + dotfolders. Skip files with descriptive human-readable names.

## Procedure

**1. Read file** to extract identifying info:
- PDFs: read text, look for dates, vendors, order/reference IDs, doc type
- Images (jpg, png, webp, gif): view via multimodal, identify what depicted
- Other formats: best-effort read; unreadable → rely on folder context alone

**2. Fix image orientation** if not right-side-up. Use `exiftool -auto-rotate` or `magick mogrify -auto-orient`. Files in `_sources/` — don't modify, add to needs-attention.md.

**3. Gather context:** folder path (strong signal), neighboring files, EXIF data. File content = ultimate truth over folder context.

**4. Generate new name** per vault naming conventions in CLAUDE.md. Date source priority:
1. File content (extracted date)
2. EXIF metadata
3. Filename-embedded date (`IMG_20160130` → `2016-01-30`)
4. Folder context (parent named `2015/`)
5. Omit date

**5. Act by confidence:**
- **High** — rename: `obsidian rename path="old/name.ext" name="new-name.ext"`. Files in `_sources/` → `I_AM_BEING_CAREFUL=1` escape hatch. Grep for old name, fix stale refs.
- **Low** — add to needs-attention.md with proposed name and reason.
