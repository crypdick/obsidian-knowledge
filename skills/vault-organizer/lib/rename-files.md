# Rename ambiguous files

## What counts as ambiguous

Look for device-generated names (`IMG_1234`, `DSC_1234`, `PXL_1234`), hashes,
numeric-only names, generic labels such as `scan` or `receipt`, and duplicate
extensions such as `.pdf.pdf`. Skip descriptive names, dotfolders, and `.trash/`.

Renames can include `_sources/` only after explicit human approval. In
Codex/Claude, use i-insist approval (`I insist`, or an explicitly authorized
`HUMAN_PERMISSION_GRANTED=1` shell call). Hermes retains its
`I_AM_BEING_CAREFUL=1` shell marker. Do not modify original file content there.

## Procedure

1. Read or view the file to identify its content. Use folder context, neighboring
   files, and metadata as supporting evidence. If unreadable, use folder context
   and lower the confidence.
2. Correct image orientation when needed with `exiftool -auto-rotate` or
   `magick mogrify -auto-orient`. For `_sources/`, record the issue in
   `needs-attention.md` instead of modifying the file.
3. Choose a descriptive name using the vault's `CLAUDE.md` conventions. Prefer
   dates from file content, then EXIF metadata, then the filename, then the
   parent folder. Omit the date when none is reliable.
4. For a confident match, rename the file:

   ```bash
   obsidian vault="$VAULT_NAME" rename path="old/name.ext" name="new-name.ext"
   ```

5. Verify the new path exists and the old path is gone. Search for the old name
   and repair stale links. For low-confidence cases, add the proposed name and
   reasoning to `needs-attention.md` instead of renaming.
