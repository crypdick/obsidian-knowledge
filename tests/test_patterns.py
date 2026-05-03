"""Unit tests for hooks/lib/patterns.py."""

import datetime

from lib import patterns


# Wikilink violations

def test_plain_md_wikilink_flagged():
    violations = patterns.find_wikilink_ext_violations("See [[foo.md]] for details.")
    assert len(violations) == 1
    assert violations[0][1] == "[[foo.md]]"


def test_aliased_md_wikilink_flagged():
    violations = patterns.find_wikilink_ext_violations("Read [[foo.md|some alias]].")
    assert len(violations) == 1


def test_pdf_attachment_not_flagged():
    violations = patterns.find_wikilink_ext_violations("See [[2024-tax.pdf]].")
    assert violations == []


def test_image_not_flagged():
    violations = patterns.find_wikilink_ext_violations("![[photo.jpg]]")
    assert violations == []


def test_no_extension_not_flagged():
    violations = patterns.find_wikilink_ext_violations("See [[foo]] and [[bar|baz]].")
    assert violations == []


def test_line_numbers_reported():
    content = "line 1\nline 2 has [[foo.md]]\nline 3\n"
    violations = patterns.find_wikilink_ext_violations(content)
    assert violations[0][0] == 2


def test_multiple_violations_on_different_lines():
    content = "[[a.md]]\n\n[[b.md|alias]]\n"
    violations = patterns.find_wikilink_ext_violations(content)
    assert len(violations) == 2
    assert violations[0][0] == 1
    assert violations[1][0] == 3


def test_skips_violations_inside_fenced_code_block():
    content = "Real: [[a.md]]\n```\nExample: [[b.md]]\n```\nReal: [[c.md]]\n"
    violations = patterns.find_wikilink_ext_violations(content)
    matches = [v[1] for v in violations]
    assert "[[a.md]]" in matches
    assert "[[c.md]]" in matches
    assert "[[b.md]]" not in matches


def test_skips_violations_in_tilde_fenced_block():
    content = "~~~\n[[fenced.md]]\n~~~\n[[real.md]]\n"
    violations = patterns.find_wikilink_ext_violations(content)
    matches = [v[1] for v in violations]
    assert matches == ["[[real.md]]"]


def test_handles_nested_long_fences():
    content = "````\n```\n[[inner.md]]\n```\n````\n[[outer.md]]\n"
    violations = patterns.find_wikilink_ext_violations(content)
    matches = [v[1] for v in violations]
    assert matches == ["[[outer.md]]"]


def test_skips_inline_code_spans():
    content = "Use `[[foo.md]]` as the wrong form, but [[bar.md]] is also wrong.\n"
    violations = patterns.find_wikilink_ext_violations(content)
    matches = [v[1] for v in violations]
    assert matches == ["[[bar.md]]"]


def test_indented_fence_still_recognized():
    content = "   ```\n[[indented.md]]\n   ```\n[[after.md]]\n"
    violations = patterns.find_wikilink_ext_violations(content)
    matches = [v[1] for v in violations]
    assert matches == ["[[after.md]]"]


# Dated-folder detection

def test_journal_path_is_dated_folder():
    assert patterns.is_in_dated_folder("Journal/2026-04-21 foo.md")


def test_diary_subfolder_is_dated_folder():
    assert patterns.is_in_dated_folder("wiki/systems/machines/dcloud/diary/foo.md")


def test_convos_subfolder_is_dated_folder():
    assert patterns.is_in_dated_folder("wiki/systems/knowledge-base/convos/foo.md")


def test_plans_subfolder_is_dated_folder():
    assert patterns.is_in_dated_folder("wiki/systems/knowledge-base/plans/foo.md")


def test_regular_wiki_path_is_not_dated():
    assert not patterns.is_in_dated_folder("wiki/systems/index.md")


def test_sources_subfolder_is_not_dated():
    assert not patterns.is_in_dated_folder("wiki/life/taxes/_sources/2024-w2.pdf")


def test_date_prefix_matches_space_separator():
    assert patterns.DATE_PREFIX_RE.match("2026-04-21 foo.md")


def test_date_prefix_matches_hyphen_separator():
    assert patterns.DATE_PREFIX_RE.match("2026-04-21-foo.md")


def test_date_prefix_rejects_no_date():
    assert not patterns.DATE_PREFIX_RE.match("foo.md")


def test_date_prefix_rejects_invalid_date():
    assert not patterns.DATE_PREFIX_RE.match("2026-13-01 foo.md")


# Frontmatter parsing

def test_valid_frontmatter_returns_dict():
    content = "---\ntitle: Foo\ndate: 2026-04-21\n---\n\nBody."
    parsed, err = patterns.parse_frontmatter(content)
    assert parsed == {"title": "Foo", "date": datetime.date(2026, 4, 21)}
    assert err is None


def test_empty_frontmatter_returns_empty_dict():
    content = "---\n---\n"
    parsed, err = patterns.parse_frontmatter(content)
    assert parsed == {}
    assert err is None


def test_no_frontmatter_returns_none():
    content = "# Just a heading\n\nBody text."
    parsed, err = patterns.parse_frontmatter(content)
    assert parsed is None
    assert err is None


def test_malformed_yaml_returns_error():
    content = "---\ntitle: [unclosed list\n---\n"
    parsed, err = patterns.parse_frontmatter(content)
    assert parsed is None
    assert err is not None


def test_only_opening_delimiter_returns_error():
    content = "---\ntitle: foo\n\nno closing."
    parsed, err = patterns.parse_frontmatter(content)
    assert parsed is None
    assert err is not None
