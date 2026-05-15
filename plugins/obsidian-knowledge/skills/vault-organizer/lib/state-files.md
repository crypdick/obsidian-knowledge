# State files

State lives at `<vault_root>/Utility/obsidian-knowledge/`. Create dir on first run if missing.

## changelog/

Per-session files. Create one new file per agent session, never append to an existing file.

**Filename:** `YYYY-MM-DD-HHMMSS-<slug>.md`
- Timestamp ensures no collision across concurrent sessions
- Slug is human-readable glance (e.g. `2026-05-12-143022-vault-organizer.md`)

**Contents:** one terse line per significant action. No H2 headers. No narrative. No code blocks.

```
YYYY-MM-DD HH:MM — Created folder/index.md (N entries)
YYYY-MM-DD HH:MM — Moved old/path.md → new/path.md
YYYY-MM-DD HH:MM — Fixed N stale links during move/rename sanity check
YYYY-MM-DD HH:MM — diary: vault reorg pass → [[wiki/systems/knowledge-base/diary/2026-05-12-reorg]]
```

Skip file entirely if no actions taken.

**Agent usage:**
```bash
ls -t Utility/obsidian-knowledge/changelog/ | head -10   # recent sessions
rg -l "syncthing" Utility/obsidian-knowledge/changelog/  # sessions touching X
```

## needs-attention.md

Living worklist for human judgment. Entries are `- [ ]` checkboxes. Delete when resolved — don't check off.

```
# Needs Attention

- [ ] `file.md:15` — unresolved link to `target.md`. Candidate: `other.md`
  covers similar topic but not confident it's the intended target
- [ ] `file.md:30` — unresolved link to `missing.md`, no matching file found
- [ ] `path/to/IMG_20161222_124409.jpg` — ambiguous filename.
  Proposed: `2016-12-22-fl-drivers-license-photo.jpg`.
  Confidence low: name derived primarily from folder context.
```
