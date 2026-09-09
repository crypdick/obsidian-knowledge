# State files

State lives at `<vault_root>/Utility/obsidian-knowledge/`. Create the directory if missing.

## changelog/

Create one file for the session. Reuse it for further actions in that session;
never append to another session's file.

Name the file `YYYY-MM-DD-HHMMSS-<slug>.md`. Use a descriptive slug, such as
`2026-05-12-143022-vault-organizer.md`.

Write one short line per significant action. Omit H2 headings, narrative, and
code blocks.

For session logs, do not create or update `changelog/index.md`. The Utility
zone is excluded from structural index enforcement. Find session records by
filename or search; a shared index risks concurrent writes.

```text
YYYY-MM-DD HH:MM — Created folder/index.md (N entries)
YYYY-MM-DD HH:MM — Moved old/path.md → new/path.md
YYYY-MM-DD HH:MM — Fixed N stale links during move/rename sanity check
YYYY-MM-DD HH:MM — diary: vault reorg pass → [[wiki/systems/knowledge-base/diary/2026-05-12-reorg]]
```

Do not create a file if no actions were taken.

## needs-attention.md

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
