from __future__ import annotations

import contextlib
import io
import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest


def run_recover(vault: Path, items: list[dict[str, str]], *args: str) -> subprocess.CompletedProcess[str]:
    from gardener.cli import main

    stdout, stderr = io.StringIO(), io.StringIO()
    command = ["links", "--vault", str(vault), *args]
    with (
        patch("sys.stdin", io.StringIO(json.dumps(items))),
        contextlib.redirect_stdout(stdout),
        contextlib.redirect_stderr(stderr),
    ):
        code = main(command)
    return subprocess.CompletedProcess(command, code, stdout.getvalue(), stderr.getvalue())


def test_classifies_unique_normalized_match_without_applying(tmp_path: Path) -> None:
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "obsidian-knowledge.yaml").write_text("ai_managed: [wiki]\n", encoding="utf-8")
    (tmp_path / "wiki").mkdir()
    (tmp_path / "wiki" / "Renamed File.md").write_text("# Renamed\n", encoding="utf-8")
    (tmp_path / "wiki" / "source.md").write_text("See [[renamed_file]].\n", encoding="utf-8")

    result = run_recover(
        tmp_path,
        [{"link": "renamed_file", "count": "1", "sources": "wiki/source.md"}],
    )

    assert "high-confidence moved/renamed file\trenamed_file" in result.stdout
    assert "wiki/Renamed File.md" in result.stdout
    assert (tmp_path / "wiki" / "source.md").read_text(encoding="utf-8") == "See [[renamed_file]].\n"


def test_skips_broken_markdown_symlinks(tmp_path: Path) -> None:
    (tmp_path / "wiki").mkdir()
    (tmp_path / "wiki" / "valid.md").write_text("# Valid\n", encoding="utf-8")
    (tmp_path / "wiki" / "broken.md").symlink_to(tmp_path / "missing.md")

    result = run_recover(tmp_path, [])

    assert result.returncode == 0


def test_apply_rewrites_only_auto_fixable_links(tmp_path: Path) -> None:
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "obsidian-knowledge.yaml").write_text("ai_managed: [wiki]\n", encoding="utf-8")
    (tmp_path / "wiki").mkdir()
    (tmp_path / "wiki" / "Renamed File.md").write_text("# Renamed\n", encoding="utf-8")
    (tmp_path / "wiki" / "source.md").write_text(
        "See [[renamed_file|display]] and [[plain concept]].\n", encoding="utf-8"
    )

    result = run_recover(
        tmp_path,
        [
            {"link": "renamed_file", "count": "1", "sources": "wiki/source.md"},
            {"link": "plain concept", "count": "1", "sources": "wiki/source.md"},
        ],
        "--apply",
    )

    assert "# applied_rewrites\t1" in result.stdout
    assert (tmp_path / "wiki" / "source.md").read_text(
        encoding="utf-8"
    ) == "See [[wiki/Renamed File|display]] and [[plain concept]].\n"


def test_path_and_date_references_are_missing_not_concept_stubs(tmp_path: Path) -> None:
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "obsidian-knowledge.yaml").write_text("ai_managed: [wiki]\n", encoding="utf-8")
    (tmp_path / "wiki").mkdir()
    (tmp_path / "wiki" / "source.md").write_text(
        "[[2026-04-05-missing]] [[scripts/foo.py]]\n", encoding="utf-8"
    )

    result = run_recover(
        tmp_path,
        [
            {"link": "2026-04-05-missing", "count": "1", "sources": "wiki/source.md"},
            {"link": "scripts/foo.py", "count": "1", "sources": "wiki/source.md"},
            {"link": "attention head", "count": "1", "sources": "wiki/source.md"},
        ],
        "--include-stubs",
    )

    assert "missing-note/date/path reference\t2026-04-05-missing" in result.stdout
    assert "missing-note/date/path reference\tscripts/foo.py" in result.stdout
    assert "likely intentional concept stub\tattention head" in result.stdout


def test_path_like_links_do_not_fall_back_to_unrelated_basename(tmp_path: Path) -> None:
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "obsidian-knowledge.yaml").write_text("ai_managed: [wiki]\n", encoding="utf-8")
    (tmp_path / "wiki" / "real").mkdir(parents=True)
    (tmp_path / "Utility" / "obsidian-knowledge").mkdir(parents=True)
    (tmp_path / "wiki" / "real" / "changelog.md").write_text("# Wrong basename\n", encoding="utf-8")
    (tmp_path / "wiki" / "source.md").write_text(
        "[[Utility/obsidian-knowledge/changelog]]\n", encoding="utf-8"
    )

    result = run_recover(
        tmp_path,
        [{"link": "Utility/obsidian-knowledge/changelog", "count": "1", "sources": "wiki/source.md"}],
        "--apply",
    )

    assert "# applied_rewrites\t0" in result.stdout
    assert "missing-note/date/path reference\tUtility/obsidian-knowledge/changelog" in result.stdout
    assert (tmp_path / "wiki" / "source.md").read_text(
        encoding="utf-8"
    ) == "[[Utility/obsidian-knowledge/changelog]]\n"


def test_ambiguous_fuzzy_candidates_are_not_applied(tmp_path: Path) -> None:
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "obsidian-knowledge.yaml").write_text("ai_managed: [wiki]\n", encoding="utf-8")
    (tmp_path / "wiki").mkdir()
    (tmp_path / "wiki" / "vault merge design.md").write_text("# A\n", encoding="utf-8")
    (tmp_path / "wiki" / "vault merge designs.md").write_text("# B\n", encoding="utf-8")
    (tmp_path / "wiki" / "source.md").write_text("[[vault merge desgn]]\n", encoding="utf-8")

    result = run_recover(
        tmp_path,
        [{"link": "vault merge desgn", "count": "1", "sources": "wiki/source.md"}],
        "--apply",
    )

    assert "# applied_rewrites\t0" in result.stdout
    assert "ambiguous candidate\tvault merge desgn" in result.stdout
    assert (tmp_path / "wiki" / "source.md").read_text(encoding="utf-8") == "[[vault merge desgn]]\n"


def test_recovers_unique_stale_prefix_and_attachment_without_changing_prose(tmp_path: Path) -> None:
    folder = tmp_path / "wiki" / "topic"
    folder.mkdir(parents=True)
    (folder / "note.md").write_text("# Note\n")
    (folder / "sheet.xlsx").write_bytes(b"attachment bytes")
    source = tmp_path / "wiki" / "source.md"
    original = "Prose [[retired/wiki/topic/note#Heading|alias]] / ![[retired/wiki/topic/sheet.xlsx]] / [[retired/wiki/topic/note^block]].\n"
    source.write_text(original)
    items = [
        {"link": "retired/wiki/topic/note", "sources": "wiki/source.md"},
        {"link": "retired/wiki/topic/sheet.xlsx", "sources": "wiki/source.md"},
    ]
    dry = run_recover(tmp_path, items)
    assert "high-confidence moved/renamed file\tretired/wiki/topic/note" in dry.stdout
    assert source.read_text() == original
    result = run_recover(tmp_path, items, "--apply")
    assert "# applied_rewrites\t3" in result.stdout
    assert (
        source.read_text()
        == "Prose [[wiki/topic/note#Heading|alias]] / ![[wiki/topic/sheet.xlsx]] / [[wiki/topic/note^block]].\n"
    )
    assert (folder / "sheet.xlsx").read_bytes() == b"attachment bytes"


def test_ambiguous_suffix_and_existing_directory_never_apply(tmp_path: Path) -> None:
    for prefix in ("one", "two"):
        folder = tmp_path / "wiki" / prefix / "topic"
        folder.mkdir(parents=True)
        (folder / "note.md").write_text("# Note\n")
    (tmp_path / "wiki" / "existing").mkdir()
    (tmp_path / "wiki" / "source.md").write_text("[[retired/topic/note]] [[wiki/existing]]\n")
    result = run_recover(
        tmp_path,
        [
            {"link": "retired/topic/note", "sources": "wiki/source.md"},
            {"link": "wiki/existing", "sources": "wiki/source.md"},
        ],
        "--apply",
    )
    assert "ambiguous candidate\tretired/topic/note" in result.stdout
    assert "# applied_rewrites\t0" in result.stdout


@pytest.mark.parametrize("candidate", [".cfg/Hidden Note.md", "wiki/node_modules/Hidden Note.md"])
def test_hidden_candidates_never_auto_fix(tmp_path: Path, candidate: str) -> None:
    path = tmp_path / candidate
    path.parent.mkdir(parents=True)
    path.write_text("# Hidden\n")
    (tmp_path / "wiki").mkdir(exist_ok=True)
    source = tmp_path / "wiki" / "source.md"
    source.write_text("[[hidden_note]]\n")
    result = run_recover(tmp_path, [{"link": "hidden_note", "sources": "wiki/source.md"}], "--apply")
    assert "# applied_rewrites\t0" in result.stdout
    assert source.read_text() == "[[hidden_note]]\n"


@pytest.mark.parametrize("source_name", ["wiki/_sources/source.md", "wiki/../private.md", "wiki/source.md"])
def test_apply_preserves_protected_traversal_and_symlink_sources(tmp_path: Path, source_name: str) -> None:
    (tmp_path / "wiki" / "_sources").mkdir(parents=True)
    (tmp_path / "wiki" / "Renamed File.md").write_text("# Renamed\n")
    source = tmp_path / source_name
    external = tmp_path.parent / f"{tmp_path.name}-external.md"
    if source_name == "wiki/source.md":
        external.write_text("[[renamed_file]]\n")
        source.symlink_to(external)
    else:
        source.write_text("[[renamed_file]]\n")
    result = run_recover(tmp_path, [{"link": "renamed_file", "sources": source_name}], "--apply")
    assert "# applied_rewrites\t0" in result.stdout
    assert source.read_text() == "[[renamed_file]]\n"


@pytest.mark.parametrize("reference", ["wiki/locked/source.md", "wiki//locked/source.md"])
def test_readonly_config_overrides_managed_zone(tmp_path: Path, reference: str) -> None:
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "obsidian-knowledge.yaml").write_text(
        "ai_managed: [wiki]\nai_readonly_folders: [wiki/locked]\n"
    )
    (tmp_path / "wiki" / "locked").mkdir(parents=True)
    (tmp_path / "wiki" / "Renamed File.md").write_text("# Renamed\n")
    source = tmp_path / "wiki" / "locked" / "source.md"
    source.write_text("[[renamed_file]]\n")
    result = run_recover(tmp_path, [{"link": "renamed_file", "sources": reference}], "--apply")
    assert "# applied_rewrites\t0" in result.stdout
    assert source.read_text() == "[[renamed_file]]\n"


def test_attachment_extension_never_uses_normalized_markdown_match(tmp_path: Path) -> None:
    (tmp_path / "wiki").mkdir()
    (tmp_path / "wiki" / "report pdf.md").write_text("# Unrelated note\n")
    source = tmp_path / "wiki" / "source.md"
    source.write_text("![[report.pdf]]\n")
    result = run_recover(tmp_path, [{"link": "report.pdf", "sources": "wiki/source.md"}], "--apply")
    assert "# applied_rewrites\t0" in result.stdout
    assert source.read_text() == "![[report.pdf]]\n"


def test_source_crlf_and_block_suffix_survive_repair(tmp_path: Path) -> None:
    (tmp_path / "wiki").mkdir()
    (tmp_path / "wiki" / "Renamed File.md").write_text("# Renamed\n")
    source = tmp_path / "wiki" / "source.md"
    source.write_bytes(b"# Source\r\n\r\n[[renamed_file^block|label]]\r\n")
    run_recover(tmp_path, [{"link": "renamed_file", "sources": "wiki/source.md"}], "--apply")
    assert source.read_bytes() == b"# Source\r\n\r\n[[wiki/Renamed File^block|label]]\r\n"


def test_note_attachment_target_collision_requires_review(tmp_path: Path) -> None:
    (tmp_path / "wiki").mkdir()
    (tmp_path / "wiki" / "report.pdf").write_bytes(b"attachment")
    (tmp_path / "wiki" / "report.pdf.md").write_text("# Note\n")
    source = tmp_path / "wiki" / "source.md"
    source.write_text("[[wiki/report.pdf]]\n")
    result = run_recover(tmp_path, [{"link": "wiki/report.pdf", "sources": "wiki/source.md"}], "--apply")
    assert "ambiguous candidate\twiki/report.pdf" in result.stdout
    assert "# applied_rewrites\t0" in result.stdout
    assert source.read_text() == "[[wiki/report.pdf]]\n"
