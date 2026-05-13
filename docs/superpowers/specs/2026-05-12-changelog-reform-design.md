# Changelog Reform: Per-Session Files + Terse Format

## Problem

`Utility/obsidian-knowledge/changelog.md` is a single append-only file. Two failure modes:

1. **Concurrent write conflicts.** Multiple agent sessions running simultaneously (same machine or different machines synced via Syncthing) both append to the same file. Syncthing creates conflict copies; same-machine sessions race on writes. The file has already logged its own conflicts, which is a sign the problem is real.
2. **Verbose entries bloat grep.** Entries have been written as full diagnostic narratives — code blocks, signal/noise analysis, multi-paragraph investigations. `grep "dcloud" changelog.md` returns 98 hits across dense prose. Agents searching for recent activity on a topic get context explosion.

## Solution

Replace single `changelog.md` with a directory of per-session files. Enforce terse 1-liner format. Migrate existing entries to new structure.

## Vault Structure

```
Utility/obsidian-knowledge/
├── changelog/                        # per-session files (new)
│   ├── 2026-05-12-143022-vault-organizer.md
│   ├── 2026-05-09-110000-syncthing-conflict-cleanup.md
│   └── ...
└── changelog-archive.md              # renamed from changelog.md (post-migration)
```

No `index.md` in `changelog/` — not a wiki folder, not maintained by vault-organizer.

## Entry Format

### Filename

```
YYYY-MM-DD-HHMMSS-<slug>.md
```

- Timestamp ensures uniqueness across concurrent sessions (no collision possible)
- Slug gives human-readable glance without opening the file
- `ls -t changelog/ | head -10` = recent history at a glance (git log analog)

### Contents

One line per significant action in the session. No H2 headers. No narrative. No code blocks. Pointers only.

```
YYYY-MM-DD HH:MM — <what happened> [→ [[wikilink]] if diary/convo note filed]
```

Example:

```
2026-05-12 14:30 — vault-organizer: fixed 6 broken index entries, updated needs-attention.md
2026-05-12 14:35 — moved 3 stray Inbox files → wiki/systems/machines/dcloud/
2026-05-12 14:40 — diary: Ollama reindex after bge-m3 setup → [[wiki/systems/knowledge-base/diary/2026-05-12-reindex-after-ollama]]
```

### What goes in changelog vs. diary

- **Changelog**: 1-liner per action, pointer to diary if one exists. Never the narrative itself.
- **Diary**: full narrative for complex investigations, incidents, debug sessions.
- Diary notes are now discoverable via semantic search (`obsidian-knowledge search`) — changelog doesn't need to duplicate their content.

### Agent usage patterns

```bash
# What happened in the last N sessions?
ls -t Utility/obsidian-knowledge/changelog/ | head -10

# Which sessions touched syncthing?
rg -l "syncthing" Utility/obsidian-knowledge/changelog/

# Read a specific session
cat Utility/obsidian-knowledge/changelog/2026-05-09-110000-syncthing-conflict-cleanup.md
```

## Files Changed in Plugin

| File | Change |
|---|---|
| `hooks/update-changelog.py` | Update `REASON` — instruct agent to create new file in `changelog/`, write terse 1-liners |
| `hooks/remind-convos.py` | Update option (1) text — same instruction |
| `skills/remember-conversations/SKILL.md` | Update procedure + format — create new file, not append to shared file |
| `skills/vault-organizer/SKILL.md` | Update Step 8 — create new file in `changelog/` |
| `skills/vault-organizer/lib/state-files.md` | Update `changelog.md` section to describe new structure |
| `lib/vault_index/cli.py` | Update exclude regex: `changelog\\.md` → `changelog/` dir pattern |
| `lib/vault_index/primer.py` | Update "update the changelog" phrase |
| `README.md` | Update documentation |

## Migration Script

New `scripts/migrate_changelog.py`:

1. Parse `changelog.md` — split on `## YYYY-MM-DD —` H2 headers
2. Each section → one file in `changelog/` dir
3. Filename derived from date + title slug (timestamp defaults to `000000` for historical entries where time is unknown)
4. Content: keep first 2-3 lines (the summary paragraph), strip verbose diagnostic body — that content already lives in diary notes
5. Rename `changelog.md` → `changelog-archive.md` when done

The archive file is retained read-only as historical record. Agents should not append to it.

## Out of Scope

- `docs/superpowers/specs/` and `docs/superpowers/plans/` historical docs — reference `changelog.md` but are historical records, not updated
- `lib/vault_index/indexer.py:28` — a comment referencing changelog, not functional
- `skills/vault-organizer/lib/broken-links.md:35` — incidental changelog reference, not instructional
