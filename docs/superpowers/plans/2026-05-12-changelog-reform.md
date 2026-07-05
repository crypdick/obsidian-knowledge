# Changelog Reform Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the single `changelog.md` append-only file with per-session files under `changelog/`, enforce terse 1-liner format, and migrate existing entries.

**Architecture:** Seven independent text edits (hooks, skills, vault index config, primer, README) plus one new migration script with tests. No shared code between tasks — each can be reviewed and committed independently. Migration script runs last, after all agent-facing instructions are updated.

**Tech Stack:** Python 3.13, pytest, uv. Vault at `/home/ricardo/Documents/obsidian`. Plugin at `/home/ricardo/src/PERSONAL/obsidian-knowledge`.

---

### Task 1: Update `update-changelog.py` hook reminder

**Files:**
- Modify: `hooks/update-changelog.py`

- [ ] **Step 1: Read current file**

```bash
cat hooks/update-changelog.py
```

- [ ] **Step 2: Replace REASON text**

Replace the `REASON` constant (lines 20–25) with:

```python
REASON = (
    "Reminder: if this session produced anything valuable for future agents to "
    "know (edits, decisions, discoveries, context, dead ends), create a new file "
    "in Utility/obsidian-knowledge/changelog/ named YYYY-MM-DD-HHMMSS-<slug>.md "
    "(e.g. 2026-05-12-143022-vault-organizer.md). "
    "Write one terse line per significant action: "
    "'YYYY-MM-DD HH:MM — <what happened> [→ [[wikilink]] if diary/convo filed]'. "
    "No narrative, no code blocks — pointers only. "
    "If nothing substantive happened or you already logged, carry on."
)
```

- [ ] **Step 3: Run tests**

```bash
cd /home/ricardo/src/PERSONAL/obsidian-knowledge && uv run pytest tests/ -v -x -q 2>&1 | tail -20
```

Expected: all pass (no tests depend on the exact REASON string).

- [ ] **Step 4: Commit**

```bash
git add hooks/update-changelog.py
git commit -m "feat: update-changelog hook instructs per-session file creation"
```

---

### Task 2: Update `remind-convos.py` hook reminder

**Files:**
- Modify: `hooks/remind-convos.py`

- [ ] **Step 1: Replace option (1) in REASON**

Change the REASON string. The current option (1) reads:
`"(1) Changelog entry — always, if anything substantive happened. "`

Replace with:
`"(1) Changelog entry — always, if anything substantive happened: create Utility/obsidian-knowledge/changelog/YYYY-MM-DD-HHMMSS-<slug>.md, one terse line per action. "`

The full replacement — only the option-(1) phrase changes, rest stays identical:

```python
REASON = (
    "Reminder: before wrapping up, consider what's worth preserving from this "
    "session. Options: (1) Changelog entry — always, if anything substantive "
    "happened: create Utility/obsidian-knowledge/changelog/YYYY-MM-DD-HHMMSS-<slug>.md, "
    "one terse line per action ('YYYY-MM-DD HH:MM — what happened [→ [[wikilink]]]'). "
    "(2) Learning page — if the session was Q&A or you explained "
    "a concept. Default for educational exchanges. Route by topic: consult "
    "the wiki's top-level index and a vault search to pick the subtree where "
    "neighboring notes already live; a dedicated learning subtree is the "
    "fallback when no better home exists. Accrete into the existing concept "
    "page or create one. (3) Diary note — if you worked through a process, "
    "incident, or debugging session worth narrating. (4) Convo note — if you "
    "produced analysis, comparisons, or decision rationales. (5) Guide — if "
    "you discovered a procedure others would need to repeat. Think especially "
    "about gotchas for future maintainers — tricky configurations, non-obvious "
    "failure modes, things that cost time to figure out. File these in the "
    "vault's wiki/ tree — NOT in ~/.claude/projects/.../memory/. The "
    "auto-memory directory is deprecated; knowledge belongs in the wiki, "
    "behavior rules belong in CLAUDE.md. Use the remember-conversations "
    "skill to file. If nothing worth preserving or you already filed, "
    "carry on."
)
```

- [ ] **Step 2: Run tests**

```bash
cd /home/ricardo/src/PERSONAL/obsidian-knowledge && uv run pytest tests/ -v -x -q 2>&1 | tail -20
```

Expected: all pass.

- [ ] **Step 3: Commit**

```bash
git add hooks/remind-convos.py
git commit -m "feat: remind-convos hook instructs per-session changelog file format"
```

---

### Task 3: Update `remember-conversations` skill

**Files:**
- Modify: `skills/remember-conversations/SKILL.md`

- [ ] **Step 1: Update the changelog entry description (line 24)**

Find and replace:

Old:
```
Append to `Utility/obsidian-knowledge/changelog.md` if session produced substance — edits, decisions, discoveries, dead ends. One line per action. Link to session notes for detail, not inline doc. Follow format from vault-organizer skill. Skip if nothing meaningful or already logged.
```

New:
```
Create `Utility/obsidian-knowledge/changelog/YYYY-MM-DD-HHMMSS-<slug>.md` if session produced substance — edits, decisions, discoveries, dead ends. Filename example: `2026-05-12-143022-vault-organizer.md`. Contents: one terse line per significant action, format `YYYY-MM-DD HH:MM — <what happened> [→ [[wikilink]] if diary/convo filed]`. No narrative, no code blocks — pointers only. Skip if nothing meaningful or already logged.
```

- [ ] **Step 2: Update the "Always" section procedure (line 191)**

Find and replace:

Old:
```
**Update changelog** — append dated entry to `Utility/obsidian-knowledge/changelog.md` summarizing actions. Link to session notes (or learning pages enriched), not inline detail.
```

New:
```
**Update changelog** — create `Utility/obsidian-knowledge/changelog/YYYY-MM-DD-HHMMSS-<slug>.md` summarizing actions as terse 1-liners. Link to session notes, not inline detail. No narrative in changelog itself.
```

- [ ] **Step 3: Run tests**

```bash
cd /home/ricardo/src/PERSONAL/obsidian-knowledge && uv run pytest tests/ -v -x -q 2>&1 | tail -20
```

Expected: all pass.

- [ ] **Step 4: Commit**

```bash
git add skills/remember-conversations/SKILL.md
git commit -m "feat: remember-conversations skill uses per-session changelog files"
```

---

### Task 4: Update vault-organizer skill and state-files

**Files:**
- Modify: `skills/vault-organizer/SKILL.md` (Step 8 section)
- Modify: `skills/vault-organizer/lib/state-files.md`

- [ ] **Step 1: Update vault-organizer Step 8**

Find in `skills/vault-organizer/SKILL.md`:
```
### Step 8: Append to changelog.md

Date-stamped entry at top of `$VAULT/Utility/obsidian-knowledge/changelog.md`. Read `lib/state-files.md` for format. Skip if no actions taken.
```

Replace with:
```
### Step 8: Create changelog entry

Create `$VAULT/Utility/obsidian-knowledge/changelog/YYYY-MM-DD-HHMMSS-<slug>.md`. Read `lib/state-files.md` for format. Skip if no actions taken.
```

- [ ] **Step 2: Update state-files.md**

Find and replace the entire `## changelog.md` section:

Old:
```
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
```

New:
```
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
```

- [ ] **Step 3: Run tests**

```bash
cd /home/ricardo/src/PERSONAL/obsidian-knowledge && uv run pytest tests/ -v -x -q 2>&1 | tail -20
```

Expected: all pass.

- [ ] **Step 4: Commit**

```bash
git add skills/vault-organizer/SKILL.md skills/vault-organizer/lib/state-files.md
git commit -m "feat: vault-organizer skill creates per-session changelog files"
```

---

### Task 5: Update vault index config

**Files:**
- Modify: `lib/vault_index/cli.py` (DEFAULT_VAULT_INDEX_TEMPLATE, line 41)
- Modify: `/home/ricardo/Documents/obsidian/.claude/obsidian-knowledge.yaml` (weights section)

- [ ] **Step 1: Update DEFAULT_VAULT_INDEX_TEMPLATE in cli.py**

Find in `lib/vault_index/cli.py` (inside the template string):
```
    - regex: "^.+/changelog\\\\.md$"
      multiplier: 0.6
```

Replace with:
```
    - regex: "^Utility/obsidian-knowledge/changelog/"
      multiplier: 0.6
```

This keeps changelog files indexed (for `rg -l` style semantic lookup) but down-weighted so they don't pollute normal wiki search results.

- [ ] **Step 2: Update live vault config**

Edit `/home/ricardo/Documents/obsidian/.claude/obsidian-knowledge.yaml`.

Find:
```yaml
    - regex: "^.+/changelog\\.md$"
      multiplier: 0.6
```

Replace with:
```yaml
    - regex: "^Utility/obsidian-knowledge/changelog/"
      multiplier: 0.6
```

- [ ] **Step 3: Run tests**

```bash
cd /home/ricardo/src/PERSONAL/obsidian-knowledge && uv run pytest tests/ -v -x -q 2>&1 | tail -20
```

Expected: all pass.

- [ ] **Step 4: Commit**

```bash
git add lib/vault_index/cli.py
git commit -m "feat: vault index weights target changelog/ dir instead of changelog.md"
```

The vault config at `/home/ricardo/Documents/obsidian/.claude/obsidian-knowledge.yaml` is not in the plugin repo — it's a vault file, committed separately or left as a local edit.

---

### Task 6: Update primer

**Files:**
- Modify: `lib/vault_index/primer.py`

- [ ] **Step 1: Update changelog reference**

Find in `lib/vault_index/primer.py` (line 45):
```python
        "File outcomes at session end (`remember-conversations` skill) and update the changelog. "
```

Replace with:
```python
        "File outcomes at session end (`remember-conversations` skill) — this creates a terse changelog entry and any diary/convo notes. "
```

- [ ] **Step 2: Run tests**

```bash
cd /home/ricardo/src/PERSONAL/obsidian-knowledge && uv run pytest tests/ -v -x -q 2>&1 | tail -20
```

Expected: all pass. The `test_recall_init_lib.py` tests check for `"remember-conversations"` and `"harness"` — both still present.

- [ ] **Step 3: Commit**

```bash
git add lib/vault_index/primer.py
git commit -m "feat: primer defers changelog format to remember-conversations skill"
```

---

### Task 7: Update README

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Update all changelog.md references**

Find and replace these three stale passages:

1. Line 34: `"- **Changelog updates** — appends a dated entry to \`changelog.md\`"`
   → `"- **Changelog updates** — creates a terse per-session file in \`changelog/\`"`

2. Lines 122–123:
   ```
   - **update-changelog.sh** — reminds the agent to append a dated entry to
     `changelog.md` if the session produced edits, decisions, or discoveries
   ```
   →
   ```
   - **update-changelog.sh** — reminds the agent to create a per-session file in
     `changelog/` if the session produced edits, decisions, or discoveries
   ```

3. Line 305: `"- \`changelog.md\` — append-only log of vault changes"`
   → `"- \`changelog/\` — per-session terse logs (one file per agent session, 1-liners only)"`

- [ ] **Step 2: Run tests**

```bash
cd /home/ricardo/src/PERSONAL/obsidian-knowledge && uv run pytest tests/ -v -x -q 2>&1 | tail -20
```

Expected: all pass.

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: update README for per-session changelog/ structure"
```

---

### Task 8: Write migration script

**Files:**
- Create: `scripts/migrate_changelog.py`
- Create: `tests/test_migrate_changelog.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_migrate_changelog.py`:

```python
"""Tests for the changelog migration script."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

from migrate_changelog import parse_entries, slugify, entry_to_filename, extract_diary_links


class TestSlugify:
    def test_lowercases_and_hyphenates(self):
        assert slugify("Conflict Cleanup Pass After Architectural Flip") == "conflict-cleanup-pass-after-architectural-flip"

    def test_strips_special_chars(self):
        assert slugify("Templater (mac-mini): fix landed") == "templater-mac-mini-fix-landed"

    def test_truncates_at_60_chars(self):
        result = slugify("A" * 100)
        assert len(result) <= 60

    def test_trims_trailing_hyphens(self):
        result = slugify("foo bar ---")
        assert not result.endswith("-")


class TestParseEntries:
    def test_splits_on_h2_headers(self):
        content = """---
created: 2026-01-01
---
# Changelog

## 2026-05-09 — First entry

Some content here.

## 2026-05-08 — Second entry

Other content.
"""
        entries = parse_entries(content)
        assert len(entries) == 2

    def test_extracts_date_and_title(self):
        content = "## 2026-05-09 — Syncthing conflict cleanup: 37 files\n\nContent."
        entries = parse_entries(content)
        assert entries[0].date == "2026-05-09"
        assert entries[0].title == "Syncthing conflict cleanup: 37 files"

    def test_empty_content_returns_no_entries(self):
        assert parse_entries("# Changelog\n\nNo entries yet.") == []


class TestExtractDiaryLinks:
    def test_finds_diary_wikilinks(self):
        body = """Full investigation.
Filed:
- Diary: [[wiki/systems/machines/dream-machine/diary/2026-05-09-daily-note-overwritten]]
- [[wiki/systems/machines/dcloud/syncthing#Diagnostic]]
"""
        links = extract_diary_links(body)
        assert "[[wiki/systems/machines/dream-machine/diary/2026-05-09-daily-note-overwritten]]" in links

    def test_returns_empty_for_no_links(self):
        assert extract_diary_links("No wikilinks here.") == []


class TestEntryToFilename:
    def test_formats_correctly(self):
        fname = entry_to_filename("2026-05-09", "Conflict cleanup pass")
        assert fname == "2026-05-09-000000-conflict-cleanup-pass.md"

    def test_handles_colons_in_title(self):
        fname = entry_to_filename("2026-05-08", "Syncthing: star topology fix")
        assert fname.startswith("2026-05-08-000000-")
        assert ":" not in fname


class TestMigration:
    def test_dry_run_creates_no_files(self, tmp_path):
        from migrate_changelog import migrate

        vault = tmp_path / "vault"
        (vault / "Utility" / "obsidian-knowledge").mkdir(parents=True)
        cl = vault / "Utility" / "obsidian-knowledge" / "changelog.md"
        cl.write_text("# Changelog\n\n## 2026-05-09 — First entry\n\nSome content.\n")

        result = migrate(vault, apply=False)

        assert result.would_create == 1
        assert not (vault / "Utility" / "obsidian-knowledge" / "changelog").exists()

    def test_apply_creates_changelog_dir_and_files(self, tmp_path):
        from migrate_changelog import migrate

        vault = tmp_path / "vault"
        (vault / "Utility" / "obsidian-knowledge").mkdir(parents=True)
        cl = vault / "Utility" / "obsidian-knowledge" / "changelog.md"
        cl.write_text(
            "# Changelog\n\n"
            "## 2026-05-09 — Syncthing conflict cleanup: 37 files\n\n"
            "Pixel 10 reported conflicts. Deleted 37.\n\n"
            "## 2026-05-08 — Pixel Watch Nextcloud calendar\n\n"
            "Wear OS blocks non-Google cals. Filed guide.\n"
        )

        result = migrate(vault, apply=True)

        changelog_dir = vault / "Utility" / "obsidian-knowledge" / "changelog"
        assert changelog_dir.is_dir()
        assert result.created == 2
        files = list(changelog_dir.glob("*.md"))
        assert len(files) == 2

    def test_apply_renames_original(self, tmp_path):
        from migrate_changelog import migrate

        vault = tmp_path / "vault"
        (vault / "Utility" / "obsidian-knowledge").mkdir(parents=True)
        cl = vault / "Utility" / "obsidian-knowledge" / "changelog.md"
        cl.write_text("# Changelog\n\n## 2026-05-09 — Test entry\n\nContent.\n")

        migrate(vault, apply=True)

        assert not cl.exists()
        assert (vault / "Utility" / "obsidian-knowledge" / "changelog-archive.md").exists()

    def test_entry_content_is_terse_one_liner(self, tmp_path):
        from migrate_changelog import migrate

        vault = tmp_path / "vault"
        (vault / "Utility" / "obsidian-knowledge").mkdir(parents=True)
        cl = vault / "Utility" / "obsidian-knowledge" / "changelog.md"
        cl.write_text(
            "# Changelog\n\n"
            "## 2026-05-09 — Syncthing conflict cleanup\n\n"
            "Long verbose paragraph about all the details.\n"
            "More verbose content.\n\n"
            "Filed:\n- Diary: [[wiki/systems/diary/2026-05-09-cleanup]]\n"
        )

        migrate(vault, apply=True)

        files = list((vault / "Utility" / "obsidian-knowledge" / "changelog").glob("*.md"))
        content = files[0].read_text()
        lines = [l for l in content.strip().splitlines() if l.strip()]
        # 1-liner + optional diary pointer = at most 2 lines
        assert len(lines) <= 2
        assert "2026-05-09" in lines[0]
        assert "Syncthing conflict cleanup" in lines[0]

    def test_idempotent_dry_run_does_not_fail_if_dir_exists(self, tmp_path):
        from migrate_changelog import migrate

        vault = tmp_path / "vault"
        (vault / "Utility" / "obsidian-knowledge" / "changelog").mkdir(parents=True)
        cl = vault / "Utility" / "obsidian-knowledge" / "changelog.md"
        cl.write_text("# Changelog\n\n## 2026-05-09 — Entry\n\nContent.\n")

        result = migrate(vault, apply=False)
        assert result.would_create == 1
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd /home/ricardo/src/PERSONAL/obsidian-knowledge && uv run pytest tests/test_migrate_changelog.py -v 2>&1 | tail -30
```

Expected: `ModuleNotFoundError: No module named 'migrate_changelog'`

- [ ] **Step 3: Write migration script**

Create `scripts/migrate_changelog.py`:

```python
#!/usr/bin/env python3
"""One-shot migration: changelog.md → per-session files in changelog/.

Parses the monolithic changelog.md, splits on H2 date headers, converts
each section to a terse 1-liner file under changelog/. Renames the original
to changelog-archive.md when done.

Usage:
    uv run python scripts/migrate_changelog.py --vault /path/to/vault   # dry-run
    uv run python scripts/migrate_changelog.py --vault /path/to/vault --apply
"""
from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Entry:
    date: str
    title: str
    body: str


@dataclass
class MigrateResult:
    would_create: int = 0
    created: int = 0
    skipped: int = 0


_WIKILINK_RE = re.compile(r'\[\[(?:diary|convos)/[^\]]+\]\]|\[\[wiki/[^\]]+/(?:diary|convos)/[^\]]+\]\]')
_H2_SPLIT_RE = re.compile(r'^## (\d{4}-\d{2}-\d{2}) — (.+)$', re.MULTILINE)
_SLUG_STRIP_RE = re.compile(r'[^a-z0-9\s-]')
_SLUG_SPACE_RE = re.compile(r'[\s_]+')
_SLUG_DASH_RE = re.compile(r'-{2,}')


def slugify(title: str, max_len: int = 60) -> str:
    s = title.lower()
    s = _SLUG_STRIP_RE.sub('', s)
    s = _SLUG_SPACE_RE.sub('-', s)
    s = _SLUG_DASH_RE.sub('-', s)
    s = s[:max_len].rstrip('-')
    return s


def entry_to_filename(date: str, title: str) -> str:
    return f"{date}-000000-{slugify(title)}.md"


def extract_diary_links(body: str) -> list[str]:
    return _WIKILINK_RE.findall(body)


def parse_entries(content: str) -> list[Entry]:
    matches = list(_H2_SPLIT_RE.finditer(content))
    if not matches:
        return []
    entries = []
    for i, m in enumerate(matches):
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(content)
        body = content[start:end].strip()
        entries.append(Entry(date=m.group(1), title=m.group(2).strip(), body=body))
    return entries


def _format_entry_content(entry: Entry) -> str:
    lines = [f"{entry.date} 00:00 — {entry.title}"]
    diary_links = extract_diary_links(entry.body)
    for link in diary_links:
        lines.append(f"  → {link}")
    return "\n".join(lines) + "\n"


def migrate(vault_root: Path, apply: bool = False) -> MigrateResult:
    utility = vault_root / "Utility" / "obsidian-knowledge"
    changelog_md = utility / "changelog.md"
    changelog_dir = utility / "changelog"
    archive = utility / "changelog-archive.md"

    if not changelog_md.exists():
        print(f"Nothing to do: {changelog_md} not found.", file=sys.stderr)
        return MigrateResult()

    content = changelog_md.read_text(encoding="utf-8")
    entries = parse_entries(content)
    result = MigrateResult()

    if not entries:
        print("No H2 entries found in changelog.md.", file=sys.stderr)
        return result

    for entry in entries:
        filename = entry_to_filename(entry.date, entry.title)
        dest = changelog_dir / filename
        if apply and dest.exists():
            result.skipped += 1
            print(f"  skip (exists): {filename}")
            continue
        result.would_create += 1
        if apply:
            changelog_dir.mkdir(exist_ok=True)
            dest.write_text(_format_entry_content(entry), encoding="utf-8")
            result.created += 1
            print(f"  create: {filename}")
        else:
            print(f"  would create: {filename}")

    if apply:
        changelog_md.rename(archive)
        print(f"\nRenamed changelog.md → changelog-archive.md")
        print(f"Done: {result.created} created, {result.skipped} skipped.")
    else:
        print(f"\nDry run: {result.would_create} entries would be created. Pass --apply to execute.")

    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vault", type=Path, default=Path.cwd(), help="Vault root (default: cwd)")
    parser.add_argument("--apply", action="store_true", help="Write files (default: dry-run)")
    args = parser.parse_args()
    migrate(args.vault, apply=args.apply)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests**

```bash
cd /home/ricardo/src/PERSONAL/obsidian-knowledge && uv run pytest tests/test_migrate_changelog.py -v 2>&1 | tail -30
```

Expected: all tests pass.

- [ ] **Step 5: Run full test suite**

```bash
cd /home/ricardo/src/PERSONAL/obsidian-knowledge && uv run pytest tests/ -v -q 2>&1 | tail -20
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add scripts/migrate_changelog.py tests/test_migrate_changelog.py
git commit -m "feat: migration script converts changelog.md to per-session changelog/ files"
```

---

### Task 9: Run migration on vault

This task touches the live vault. Run only after Tasks 1–8 are complete.

**Files:**
- Vault: `/home/ricardo/Documents/obsidian/Utility/obsidian-knowledge/changelog.md` → renamed to `changelog-archive.md`
- Vault: `/home/ricardo/Documents/obsidian/Utility/obsidian-knowledge/changelog/` created with migrated entries

- [ ] **Step 1: Dry run**

```bash
cd /home/ricardo/src/PERSONAL/obsidian-knowledge && uv run python scripts/migrate_changelog.py --vault /home/ricardo/Documents/obsidian 2>&1 | head -30
```

Expected: list of filenames that would be created, ending with `Dry run: N entries would be created.`

- [ ] **Step 2: Review dry-run output**

Spot-check a few filenames: do the date + slug match the original H2 headers? Verify N matches expected entry count (should be ~30–40 entries based on current changelog length).

- [ ] **Step 3: Apply migration**

```bash
cd /home/ricardo/src/PERSONAL/obsidian-knowledge && uv run python scripts/migrate_changelog.py --vault /home/ricardo/Documents/obsidian --apply
```

Expected: files created, `changelog.md` renamed to `changelog-archive.md`.

- [ ] **Step 4: Verify output**

```bash
ls -t /home/ricardo/Documents/obsidian/Utility/obsidian-knowledge/changelog/ | head -10
cat /home/ricardo/Documents/obsidian/Utility/obsidian-knowledge/changelog/$(ls -t /home/ricardo/Documents/obsidian/Utility/obsidian-knowledge/changelog/ | head -1)
```

Expected: recent filenames with date+slug pattern; file contents are terse 1-liners.

- [ ] **Step 5: Version bump plugin**

The plugin has a hookify rule requiring a version bump for any change. Bump patch version in `.claude-plugin/plugin.json`:

```bash
cat /home/ricardo/src/PERSONAL/obsidian-knowledge/.claude-plugin/plugin.json
```

Increment the `version` field by one patch (e.g., `3.8.1` → `3.8.2`).

- [ ] **Step 6: Commit plugin version bump**

```bash
cd /home/ricardo/src/PERSONAL/obsidian-knowledge && git add .claude-plugin/plugin.json && git commit -m "chore: bump version for changelog reform"
```

- [ ] **Step 7: Write changelog entry for this session**

Create `/home/ricardo/Documents/obsidian/Utility/obsidian-knowledge/changelog/2026-05-12-HHMMSS-changelog-reform.md` (use actual current time for HHMMSS):

```
2026-05-12 HH:MM — changelog reform: migrated changelog.md → changelog/ per-session files, updated hooks + skills + vault index config
```
