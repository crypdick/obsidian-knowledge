# State files

State lives at `<vault_root>/Utility/obsidian-knowledge/`. Create dir on first run if missing.

## changelog.md

Append-only log. Add date-stamped section at top after each run. One line per action.

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

Skip entry entirely if no actions taken.

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
