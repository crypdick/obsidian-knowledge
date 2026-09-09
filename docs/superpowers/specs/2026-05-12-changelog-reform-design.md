# Changelog Reform: Per-Session Files + Terse Format

## Problem

`Utility/obsidian-knowledge/changelog.md` is a single append-only file with two
problems:

1. Concurrent sessions append to the same file. Writes race on the same machine,
   and Syncthing creates conflict copies across machines. The changelog already
   records these conflicts.
2. Entries contain full investigations, including code blocks and several
   paragraphs of analysis. `grep "dcloud" changelog.md` returns 98 hits, making
   recent activity on a topic hard to find.

## Solution

Replace `changelog.md` with a directory containing one file per session and one
short line per action. Migrate existing entries to this structure.

## Vault Structure

```
Utility/obsidian-knowledge/
├── changelog/                        # per-session files (new)
│   ├── 2026-05-12-143022-vault-organizer.md
│   ├── 2026-05-09-110000-syncthing-conflict-cleanup.md
│   └── ...
└── changelog-archive.md              # renamed from changelog.md (post-migration)
```

Do not create `index.md` in `changelog/`; the directory is outside the wiki and
is not maintained by vault-organizer.

## Entry Format

### Filename

```
YYYY-MM-DD-HHMMSS-<slug>.md
```

- The timestamp and slug distinguish session files. Sessions using the same
  slug within the same second can still collide.
- The slug describes the session without requiring the reader to open the file.
- `ls -t changelog/ | head -10` lists the ten most recently modified files.

### Contents

Write one short line per significant action, with links to detailed notes.
Omit H2 headings, narrative, and code blocks.

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

Keep action summaries and links in the changelog. Put full accounts of complex
investigations, incidents, and debugging sessions in diary notes. Those notes
are discoverable through `obsidian-knowledge search`, so the changelog does not
need to repeat them.

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
