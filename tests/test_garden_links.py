"""Conservative recovery behavior beyond the installed-CLI integration cases."""

from __future__ import annotations

import io
import json
import re
from pathlib import Path

import pytest

from gardener import links
from gardener.io import OrganizerPolicy
from gardener.models import NoteCandidate, RecoveryDecision, UnresolvedItem


@pytest.mark.parametrize(
    "text, expected",
    [
        ("# No frontmatter\n", ()),
        ("---\naliases: Missing close\n", ()),
        ("---\naliases: [broken\n---\n", ()),
        ("---\n- scalar-list\n---\n", ()),
        ("---\naliases: 12\n---\n", ()),
        ("---\n---\n", ()),
        ("---\naliases: Old Name\n---\n", ("Old Name",)),
        ("---\naliases: [Old Name, '', 12]\n---\n", ("Old Name", "12")),
    ],
)
def test_frontmatter_aliases_tolerate_invalid_and_nonmapping_yaml(
    text: str, expected: tuple[str, ...]
) -> None:
    assert links.frontmatter_aliases(text) == expected


def test_alias_recovery_is_unique_and_conflicts_require_review(tmp_path: Path) -> None:
    folder = tmp_path / "wiki"
    folder.mkdir()
    (folder / "new.md").write_text("---\naliases: Old Name\n---\n# New\n")
    item = UnresolvedItem("old_name")
    decision = links.classify(item, ("wiki/source.md",), links.build_index(tmp_path), ())
    assert decision is not None
    assert decision.classification == "high-confidence moved/renamed file"
    assert decision.auto_fixable
    assert links.replacement_for(decision) == "wiki/new"
    (folder / "other.md").write_text("---\naliases: Old Name\n---\n# Other\n")
    conflict = links.classify(item, ("wiki/source.md",), links.build_index(tmp_path), ())
    assert conflict is not None
    assert conflict.classification == "ambiguous candidate"
    assert not conflict.auto_fixable


def test_exact_basename_collision_requires_review(tmp_path: Path) -> None:
    for name in ("first", "second"):
        folder = tmp_path / "wiki" / name
        folder.mkdir(parents=True)
        (folder / "note.md").write_text("# Note\n")
    decision = links.classify(UnresolvedItem("note"), ("wiki/source.md",), links.build_index(tmp_path), ())
    assert decision is not None
    assert decision.classification == "ambiguous candidate"
    assert {c.rel_path for c in decision.candidates} == {"wiki/first/note.md", "wiki/second/note.md"}


@pytest.mark.parametrize("relative", ["wiki/../note", "wiki//note", "wiki/_sources/note"])
def test_unsafe_target_paths_are_reported_without_candidates(tmp_path: Path, relative: str) -> None:
    decision = links.classify(UnresolvedItem(relative), ("wiki/source.md",), links.build_index(tmp_path), ())
    assert decision is not None
    assert decision.rationale == "unsafe target path"
    assert not decision.auto_fixable


@pytest.mark.parametrize(
    "target",
    [
        "wiki/bad|label.md",
        "wiki/bad#heading.md",
        "wiki/bad^block.md",
        "wiki/bad\nline.md",
        "wiki/bad\rline.md",
        "wiki/bad[name].md",
    ],
)
def test_unsafe_wikilink_candidate_names_are_never_auto_applied(target: str) -> None:
    candidate = NoteCandidate(target, "note", ())
    decision = RecoveryDecision("exact filename recovery", "note", ("wiki/source.md",), (candidate,))
    assert not decision.auto_fixable


def test_rewrite_no_match_and_unchanged_target_preserve_source(tmp_path: Path) -> None:
    folder = tmp_path / "wiki"
    folder.mkdir()
    source = folder / "source.md"
    original = "# Source\n[[note|alias]]\n"
    source.write_text(original)
    assert links.rewrite_source(tmp_path, "wiki/source.md", "absent", "new") == 0
    assert links.rewrite_source(tmp_path, "wiki/source.md", "note", "note") == 0
    assert source.read_text() == original


def test_managed_sources_omit_missing_nonmarkdown_and_outside_zones(tmp_path: Path) -> None:
    (tmp_path / "wiki").mkdir()
    (tmp_path / "wiki/source.md").write_text("# Source\n")
    (tmp_path / "wiki/image.png").write_bytes(b"image")
    item = UnresolvedItem("note", sources="wiki/source.md, wiki/absent.md, wiki/image.png, Notes/source.md, ")
    assert links.managed_sources(item, OrganizerPolicy(), tmp_path) == ("wiki/source.md",)
    assert links.classify(item, (), links.build_index(tmp_path), ()) is None


def test_fuzzy_recovery_does_not_invent_match_for_empty_name(tmp_path: Path) -> None:
    (tmp_path / "wiki").mkdir()
    (tmp_path / "wiki/attachment.pdf").write_bytes(b"attachment")
    decision = links.classify(UnresolvedItem("___"), ("wiki/source.md",), links.build_index(tmp_path), ())
    assert decision is not None
    assert decision.classification == "likely intentional concept stub"
    assert decision.candidates == ()


def test_link_stems_preserve_basename_and_remove_suffixes() -> None:
    assert links.link_stem("wiki/note.md#Heading") == "note"
    assert links.link_stem("wiki/note^block") == "note"
    assert links.normalize_name("WIKI/Old_Name.md") == "old name"


def test_stub_patterns_and_template_placeholders_are_classified(tmp_path: Path) -> None:
    patterns = (re.compile(r"^skip:"),)
    for name in ("skip:reference", "{{placeholder}}", "<%template%>"):
        decision = links.classify(
            UnresolvedItem(name), ("wiki/source.md",), links.build_index(tmp_path), patterns
        )
        assert decision is not None
        assert decision.rationale == "matches configured stub/template pattern"
        assert not decision.auto_fixable


def test_json_reports_include_review_information(tmp_path: Path, capsys) -> None:
    candidate = NoteCandidate("wiki/note.md", "note", ())
    decision = RecoveryDecision(
        "exact filename recovery", "note", ("wiki/source.md",), (candidate,), 1.0, "unique basename match"
    )
    links.emit([decision], "json")
    assert json.loads(capsys.readouterr().out) == [
        {
            "classification": "exact filename recovery",
            "link": "note",
            "sources": ["wiki/source.md"],
            "candidates": ["wiki/note.md"],
            "score": 1.0,
            "rationale": "unique basename match",
            "auto_fixable": True,
        }
    ]


def test_command_filters_stubs_and_unmanaged_sources(tmp_path: Path, monkeypatch, capsys) -> None:
    (tmp_path / "wiki").mkdir()
    (tmp_path / "wiki/source.md").write_text("# Source\n")
    items = [
        {"link": "plain concept", "sources": "wiki/source.md"},
        {"link": "outside", "sources": "Notes/source.md"},
    ]
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(items)))
    links.main(["--vault", str(tmp_path), "--format", "json"])
    assert json.loads(capsys.readouterr().out) == []
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(items)))
    links.main(["--vault", str(tmp_path), "--format", "json", "--include-stubs"])
    assert [d["link"] for d in json.loads(capsys.readouterr().out)] == ["plain concept"]


def test_unresolved_input_rejects_nonobject_values() -> None:
    with pytest.raises(ValueError, match="expected unresolved item object, got str"):
        UnresolvedItem.from_json("note")


def test_command_rejects_nonarray_input(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO('{"link":"note"}'))
    with pytest.raises(ValueError, match="unresolved input must be a JSON array"):
        links.main(["--vault", str(tmp_path)])


def test_command_applies_only_exact_recoveries_and_preserves_suffixes(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    folder = tmp_path / "wiki/topic"
    folder.mkdir(parents=True)
    (folder / "note.md").write_text("# Note\n")
    (folder / "Renamed Note.md").write_text("# Renamed\n")
    (folder / "note.pdf").write_bytes(b"pdf")
    source = tmp_path / "wiki/source.md"
    source.write_text(
        "[[note]] [[renamed_note#Heading|alias]] ![[retired/topic/note.pdf]] [[missing.path]] [[2026-01-01]]\n"
    )
    items = [
        {"link": name, "sources": "wiki/source.md"}
        for name in ("note", "renamed_note", "retired/topic/note.pdf", "missing.path", "2026-01-01")
    ]
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(items)))
    links.main(["--vault", str(tmp_path), "--apply"])
    assert (
        source.read_text()
        == "[[note]] [[wiki/topic/Renamed Note#Heading|alias]] ![[wiki/topic/note.pdf]] [[missing.path]] [[2026-01-01]]\n"
    )
    output = capsys.readouterr().out
    assert "# applied_rewrites\t2" in output
    assert "exact filename recovery\tnote" in output
    assert "missing-note/date/path reference\t2026-01-01" in output


def test_existing_path_is_exact_and_missing_prefix_can_be_ambiguous(tmp_path: Path) -> None:
    for prefix in ("one", "two"):
        folder = tmp_path / "wiki" / prefix / "topic"
        folder.mkdir(parents=True)
        (folder / "note.md").write_text("# Note\n")
    index = links.build_index(tmp_path)
    exact = links.classify(UnresolvedItem("wiki/one/topic/note.md"), ("wiki/source.md",), index, ())
    assert exact is not None and exact.classification == "exact filename recovery"
    assert links.replacement_for(exact) == "wiki/one/topic/note"
    ambiguous = links.classify(UnresolvedItem("retired/topic/note"), ("wiki/source.md",), index, ())
    assert ambiguous is not None and ambiguous.classification == "ambiguous candidate"
    (tmp_path / "wiki/existing").mkdir()
    missing = links.classify(UnresolvedItem("wiki/existing"), ("wiki/source.md",), index, ())
    assert missing is not None and missing.classification == "missing-note/date/path reference"


def test_fuzzy_matches_require_review_and_ignore_attachments(tmp_path: Path) -> None:
    folder = tmp_path / "wiki"
    folder.mkdir()
    (folder / "vault merge design.md").write_text("# Design\n")
    (folder / "vault merge designs.md").write_text("# Designs\n")
    (folder / "vault merge desgn.pdf").write_bytes(b"pdf")
    decision = links.classify(
        UnresolvedItem("vault merge desgn"), ("wiki/source.md",), links.build_index(tmp_path), ()
    )
    assert decision is not None
    assert decision.classification == "ambiguous candidate"
    assert not decision.auto_fixable
    assert {c.rel_path for c in decision.candidates} == {"wiki/vault merge design.md"}


def test_managed_sources_refuse_readonly_notes(tmp_path: Path) -> None:
    folder = tmp_path / "wiki/locked"
    folder.mkdir(parents=True)
    (folder / "source.md").write_text("[[note]]\n")
    config = tmp_path / ".claude/obsidian-knowledge.yaml"
    config.parent.mkdir()
    config.write_text("ai_readonly_folders: [wiki/locked]\n")
    assert (
        links.managed_sources(
            UnresolvedItem("note", sources="wiki/locked/source.md"), OrganizerPolicy.load(tmp_path), tmp_path
        )
        == ()
    )


def test_recovery_index_tolerates_file_removed_during_scan(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "wiki/note.md"
    path.parent.mkdir()
    path.write_text("# Note\n")
    original = Path.read_text

    def removed_while_reading(self: Path, *args, **kwargs):
        if self == path:
            raise FileNotFoundError("file removed by sync")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", removed_while_reading)
    assert links.build_index(tmp_path).all_candidates == ()


def test_missing_markdown_and_multicomponent_paths_stay_missing(tmp_path: Path) -> None:
    for reference in ("missing.md", "retired/missing/note"):
        decision = links.classify(
            UnresolvedItem(reference), ("wiki/source.md",), links.build_index(tmp_path), ()
        )
        assert decision is not None
        assert decision.classification == "missing-note/date/path reference"


def test_recovery_removes_multiple_stale_prefix_components(tmp_path: Path) -> None:
    folder = tmp_path / "wiki/topic"
    folder.mkdir(parents=True)
    (folder / "note.md").write_text("# Note\n")
    decision = links.classify(
        UnresolvedItem("retired/obsolete/topic/note"), ("wiki/source.md",), links.build_index(tmp_path), ()
    )
    assert decision is not None
    assert decision.classification == "high-confidence moved/renamed file"
    assert links.replacement_for(decision) == "wiki/topic/note"
