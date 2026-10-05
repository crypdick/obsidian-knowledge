"""Public audit and question-report behavior across vault maintenance cases."""

from __future__ import annotations

from pathlib import Path

import pytest

from gardener.audit import has_stacked_frontmatter
from gardener.cli import main
from gardener.questions import QuestionHit, render_report, scan_file


@pytest.mark.parametrize(
    ("operation", "argument"),
    [
        ("audit", "--vault"),
        ("links", "--format"),
        ("index", "index_path"),
        ("questions", "--timestamp"),
        ("frontmatter", "paths"),
    ],
)
def test_operation_help_exposes_its_arguments(operation: str, argument: str, capsys) -> None:
    with pytest.raises(SystemExit) as error:
        main([operation, "--help"])
    assert error.value.code == 0
    assert argument in capsys.readouterr().out


@pytest.mark.parametrize(
    ("content", "stacked"),
    [
        ("", False),
        ("# Ordinary note\n", False),
        ("---\ncreated: today\n", False),
        ("---\ncreated: today\n---\n", False),
        ("---\ncreated: today\n---\n\n# Note\n", False),
        ("---\ncreated: today\n---\n\n---\n---\n# Note\n", True),
        ("---\n" + "key: value\n" * 61 + "---\n---\n", False),
    ],
)
def test_audit_frontmatter_detection(tmp_path: Path, content: str, stacked: bool) -> None:
    path = tmp_path / "note.md"
    path.write_text(content)
    assert has_stacked_frontmatter(path) is stacked


def test_audit_disappearing_file_has_no_frontmatter_finding(tmp_path: Path) -> None:
    assert has_stacked_frontmatter(tmp_path / "missing.md") is False


def test_clean_combined_audit_does_not_modify_notes(tmp_path: Path, capsys) -> None:
    (tmp_path / "wiki").mkdir()
    note = tmp_path / "wiki/note.md"
    index = tmp_path / "wiki/index.md"
    note.write_text("# Note\n")
    index.write_text("# Wiki\n\n- [[note]] — note\n")
    (tmp_path / "wiki/.hidden.md").write_text("[[ignored.md]]\n")
    (tmp_path / "wiki/note.sync-conflict-20261003-120000-host.md").write_text("[[ignored.md]]\n")
    assert main(["audit", "--vault", str(tmp_path)]) == 0
    assert capsys.readouterr().out == "OK: no structural or convention issues found\n"
    assert note.read_text() == "# Note\n"
    assert index.read_text() == "# Wiki\n\n- [[note]] — note\n"


@pytest.mark.parametrize(
    ("location", "override", "expected"),
    [("outside", False, "First"), ("second/wiki", False, "Second"), ("second/wiki", True, "First")],
)
def test_garden_uses_registered_default_without_environment_overrides(
    tmp_path: Path, monkeypatch, capsys, location: str, override: bool, expected: str
) -> None:
    first, second = tmp_path / "first", tmp_path / "second"
    for vault, label in ((first, "First"), (second, "Second")):
        (vault / "wiki").mkdir(parents=True)
        (vault / "wiki/note.md").write_text(f"# Note\n> [!question]\n> {label} vault?\n")
    registry = tmp_path / ".config/obsidian-knowledge/vaults.yaml"
    registry.parent.mkdir(parents=True)
    registry.write_text(f"vaults:\n  - {first}\n  - {second}\n")
    (tmp_path / "outside").mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.delenv("OBSIDIAN_KNOWLEDGE_VAULTS_CONFIG", raising=False)
    monkeypatch.chdir(tmp_path / location)
    args = ["questions", "--vault", str(first)] if override else ["questions"]
    assert main(args) == 0
    assert capsys.readouterr().out == f"wiki/note.md\t2\t{expected} vault?\n"


def test_audit_managed_structure_and_vault_wide_content(tmp_path: Path, capsys) -> None:
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude/obsidian-knowledge.yaml").write_text("ai_managed: [records, Utility]\n")
    (tmp_path / "records").mkdir()
    (tmp_path / "records/note.md").write_text("# Managed\n")
    (tmp_path / "Utility").mkdir()
    (tmp_path / "Utility/note.md").write_text("# Derivative\n")
    (tmp_path / "personal").mkdir()
    (tmp_path / "personal/note.md").write_text("---\ncreated: today\n---\n\n---\n---\n[[bad.md]]\n")
    main(["audit", "--vault", str(tmp_path)])
    output = capsys.readouterr().out
    assert f"MISSING_INDEX\t{tmp_path / 'records'}" in output
    assert f"STACKED_FRONTMATTER\t{tmp_path / 'personal/note.md'}" in output
    assert "WIKILINK_EXT\tpersonal/note.md:7\t[[bad.md]]" in output
    assert f"MISSING_INDEX\t{tmp_path / 'personal'}" not in output
    assert f"MISSING_INDEX\t{tmp_path / 'Utility'}" not in output


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        ("> [!question]\n> \n> Why?\n", [(1, "Why?")]),
        ("> [!question]\nBody\n", [(1, "")]),
        ("> [!question]\n", [(1, "")]),
        ("```md\n> [!question]\n> Example?\n```\n> [!question]\n> Real?\n", [(5, "Real?")]),
        ("~~~md\n> [!question]\n```\n> Hidden?\n~~~\n", []),
    ],
)
def test_question_scanner_ignores_examples_and_handles_empty_callouts(
    tmp_path: Path, content: str, expected: list[tuple[int, str]]
) -> None:
    path = tmp_path / "note.md"
    path.write_text(content)
    assert scan_file(path) == expected


def test_question_scanner_disappearing_file_is_skipped(tmp_path: Path) -> None:
    assert scan_file(tmp_path / "missing.md") == []


@pytest.mark.parametrize("ending", ["", "\n", "\n\n"])
def test_question_report_preserves_header_and_normalizes_entry_separator(ending: str) -> None:
    before = "# Custom\n\n**Last run:** old\n\n## Scope\n\nKeep this." + ending
    hits = (QuestionHit(path="wiki/note.md", line=3, text='Why "now"?'),)
    result = render_report(before, hits, "2026-10-03T12:00:00-07:00")
    assert result == (
        "# Custom\n\n**Last run:** 2026-10-03T12:00:00-07:00\n\n## Scope\n\nKeep this.\n\n"
        '- [[wiki/note]] — line 3 — "Why \\"now\\"?"\n'
    )


@pytest.mark.parametrize(
    ("before", "message"),
    [
        ("# Report\n", "exactly one"),
        ("**Last run:** one\n**Last run:** two\n", "exactly one"),
        ('**Last run:** old\n- [[wiki/note]] — line 1 — "Old?"\nHuman text\n', "refusing to discard"),
    ],
)
def test_question_report_refuses_ambiguous_headers_and_trailing_content(before: str, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        render_report(before, (), "2026-10-03T12:00:00-07:00")


@pytest.mark.parametrize(
    "args",
    [
        ["--report", "wiki/other.md"],
        ["--report", "--timestamp", "2026-10-03T12:00:00"],
    ],
)
def test_question_command_refuses_wrong_destination_or_naive_timestamp(
    tmp_path: Path, args: list[str]
) -> None:
    with pytest.raises(SystemExit) as error:
        main(["questions", "--vault", str(tmp_path), *args])
    assert error.value.code == 1
    assert not (tmp_path / "wiki/other.md").exists()
    assert not (tmp_path / "Utility").exists()
