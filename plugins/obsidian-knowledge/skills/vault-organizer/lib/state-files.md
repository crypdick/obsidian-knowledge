# State files

State lives at `<vault_root>/Utility/obsidian-knowledge/`. Create the directory if missing.
Use the configured vault root, not its `wiki/` subdirectory. `Utility/` and
`wiki/` are siblings. Pass `Utility/obsidian-knowledge/...` unchanged to
`obsidian-knowledge write`, regardless of cwd; never prepend `wiki/`.

## `changelog/`

Log consequential structural or operational changes that could help explain
future inconsistent state. Routine note, index, and link edits need no fragment.
When logging is warranted, create one file for the session and reuse it;
never append to another session's file.

Name the file `YYYY-MM-DD-HHMMSS-<slug>.md`. Use a descriptive slug, such as
`2026-05-12-143022-vault-organizer.md`.

Write one short line per significant action. Omit H2 headings, narrative, and
code blocks.

For session logs, do not create or update `changelog/index.md`. The Utility
zone is excluded from structural index enforcement. Find session records by
filename or search; a shared index risks concurrent writes.

```text
YYYY-MM-DD HH:MM — Migrated wiki/old-system/ → wiki/new-system/
YYYY-MM-DD HH:MM — diary: vault reorg pass → [[wiki/systems/knowledge-base/diary/2026-05-12-reorg]]
```

If no consequential change occurred, do not create a file.

## `needs-attention.md`

Use `- [ ]` entries for issues requiring human judgment. Delete resolved entries.

```markdown
# Needs attention

- [ ] `file.md:15` — unresolved link to `target.md`. Candidate: `other.md`
  covers similar topic but not confident it's the intended target
- [ ] `file.md:30` — unresolved link to `missing.md`, no matching file found
- [ ] `path/to/IMG_20161222_124409.jpg` — ambiguous filename.
  Proposed: `2016-12-22-fl-drivers-license-photo.jpg`.
  Confidence low: name derived primarily from folder context.
```
