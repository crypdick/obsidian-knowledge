"""Tests for the changelog migration script."""
from __future__ import annotations

import sys
from pathlib import Path


SCRIPTS = Path(__file__).parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

from migrate_changelog import parse_entries, slugify, entry_to_filename, extract_diary_links  # noqa: E402  (needs sys.path insert above)


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
        assert len(links) == 1  # syncthing link excluded (no /diary/ or /convos/)

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
        lines = [line for line in content.strip().splitlines() if line.strip()]
        # 1-liner + optional diary pointer = at most 2 lines
        assert len(lines) <= 2
        assert "2026-05-09" in lines[0]
        assert "Syncthing conflict cleanup" in lines[0]

    def test_entry_with_multiple_diary_links_is_single_line(self, tmp_path):
        from migrate_changelog import migrate

        vault = tmp_path / "vault"
        (vault / "Utility" / "obsidian-knowledge").mkdir(parents=True)
        cl = vault / "Utility" / "obsidian-knowledge" / "changelog.md"
        cl.write_text(
            "# Changelog\n\n"
            "## 2026-05-09 — Multi-link session\n\n"
            "Filed diary and convo:\n"
            "- [[wiki/systems/diary/2026-05-09-thing]]\n"
            "- [[wiki/research/convos/2026-05-09-other]]\n"
        )

        migrate(vault, apply=True)

        files = list((vault / "Utility" / "obsidian-knowledge" / "changelog").glob("*.md"))
        lines = [line for line in files[0].read_text().strip().splitlines() if line.strip()]
        assert len(lines) == 1
        assert "→ [[wiki/systems/diary/2026-05-09-thing]]" in lines[0]
        assert "→ [[wiki/research/convos/2026-05-09-other]]" in lines[0]

    def test_idempotent_dry_run_does_not_fail_if_dir_exists(self, tmp_path):
        from migrate_changelog import migrate

        vault = tmp_path / "vault"
        (vault / "Utility" / "obsidian-knowledge" / "changelog").mkdir(parents=True)
        cl = vault / "Utility" / "obsidian-knowledge" / "changelog.md"
        cl.write_text("# Changelog\n\n## 2026-05-09 — Entry\n\nContent.\n")

        result = migrate(vault, apply=False)
        assert result.would_create == 1

    def test_apply_skips_existing_files(self, tmp_path):
        from migrate_changelog import migrate

        vault = tmp_path / "vault"
        (vault / "Utility" / "obsidian-knowledge").mkdir(parents=True)
        # Pre-create the target directory and one output file
        changelog_dir = vault / "Utility" / "obsidian-knowledge" / "changelog"
        changelog_dir.mkdir()
        (changelog_dir / "2026-05-09-000000-test-entry.md").write_text("existing\n")
        # Create changelog.md with the same entry
        cl = vault / "Utility" / "obsidian-knowledge" / "changelog.md"
        cl.write_text("# Changelog\n\n## 2026-05-09 — Test entry\n\nContent.\n")

        result = migrate(vault, apply=True)

        assert result.skipped == 1
        assert result.created == 0
        # changelog.md preserved — rename only fires when at least one file was created
        assert cl.exists()
