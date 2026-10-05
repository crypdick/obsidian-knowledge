from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]


def run_garden(name: str, vault: Path, *args: str, input_text: str = "") -> subprocess.CompletedProcess[str]:
    from gardener.cli import main

    stdout, stderr = io.StringIO(), io.StringIO()
    command = [name, "--vault", str(vault), *args]
    with (
        patch("sys.stdin", io.StringIO(input_text)),
        contextlib.redirect_stdout(stdout),
        contextlib.redirect_stderr(stderr),
    ):
        try:
            code = main(command)
        except SystemExit as exc:
            code = int(exc.code or 0)
    return subprocess.CompletedProcess(command, code, stdout.getvalue(), stderr.getvalue())


def test_audit_requires_child_index_not_descendant_link(tmp_path: Path) -> None:
    child = tmp_path / "wiki" / "topic" / "child"
    child.mkdir(parents=True)
    (child / "note.md").write_text("# Note\n")
    (child / "index.md").write_text("# Child\n\n- [[note#Section]] — note\n")
    (child.parent / "index.md").write_text("# Topic\n\n- [[wiki/topic/child/note]] — note\n")
    result = run_garden("audit", tmp_path)
    assert result.returncode == 0
    assert f"NOT_INDEXED\t{child.parent / 'index.md'}\tentry=child/" in result.stdout
    assert "entry=note.md" not in result.stdout
    (child.parent / "index.md").write_text("# Topic\n\n- [[child/index|Child]] — notes\n")
    assert "entry=child/" not in run_garden("audit", tmp_path).stdout


def test_audit_distinguishes_empty_and_typed_folders(tmp_path: Path) -> None:
    diary = tmp_path / "wiki" / "diary"
    (diary / "archive").mkdir(parents=True)
    (diary / "archive" / "entry.md").write_text("# Archived\n")
    (diary / "archive" / "index.md").write_text("# Archive\n\n- [[entry]] — archived\n")
    (tmp_path / "wiki" / "empty").mkdir()
    (tmp_path / "wiki" / "index.md").write_text("# Wiki\n\n- [[diary/index]] — diary\n")
    links = "".join(f"- [[2026-01-0{i}]] — entry\n" for i in range(1, 5))
    (diary / "index.md").write_text("# Diary\n\n- [[archive/index]] — archive\n" + links)
    for i in range(1, 5):
        (diary / f"2026-01-0{i}.md").write_text("# Entry\n")
    result = run_garden("audit", tmp_path)
    assert result.returncode == 0
    assert "\nDUMPING_GROUND\t" not in result.stdout
    assert f"EMPTY_FOLDER\t{tmp_path / 'wiki' / 'empty'}" in result.stdout
    assert "entry=empty/" not in result.stdout
    assert "\nMISSING_INDEX\t" not in result.stdout


def test_audit_still_flags_misplaced_dates_and_ancestor_name_collision(tmp_path: Path) -> None:
    folder = tmp_path / "wiki" / "topic"
    (folder / "child").mkdir(parents=True)
    (folder / "child" / "note.md").write_text("# Note\n")
    (folder / "child" / "index.md").write_text("# Child\n\n- [[note]] — note\n")
    links = "- [[wiki/topic/child/index]] — child\n"
    for i in range(1, 5):
        (folder / f"2026-01-0{i}.md").write_text("# Entry\n")
        links += f"- [[2026-01-0{i}]] — entry\n"
    (folder / "topic.md").write_text("# Topic note\n")
    (folder / "index.md").write_text("# Topic\n\n" + links)
    result = run_garden("audit", tmp_path)
    assert f"\nDUMPING_GROUND\t{folder}\tmisplaced=4" in result.stdout
    assert f"NOT_INDEXED\t{folder / 'index.md'}\tentry=topic.md" in result.stdout


def test_index_editor_preserves_sections_and_dry_run(tmp_path: Path) -> None:
    folder = tmp_path / "wiki" / "topic"
    (folder / "child").mkdir(parents=True)
    (folder / "child" / "index.md").write_text("# Child\n")
    (folder / "alpha.md").write_text("# Alpha\n")
    (folder / "zeta.md").write_text("# Zeta\n")
    index = folder / "index.md"
    original = "# Topic\n\nIntro stays.\n\n## Notes\n\n- [[zeta]] — last\n\n## Related\n\nRelated prose stays.\n- [[wiki/elsewhere]] — related\n"
    index.write_text(original)
    plan = json.dumps(
        {
            "section": "Notes",
            "entries": [
                {"target": "wiki/topic/alpha", "description": "first"},
                {"target": "wiki/topic/child/index", "label": "Child", "description": "children"},
            ],
        }
    )
    result = run_garden("index", tmp_path, "wiki/topic/index.md", input_text=plan)
    assert result.returncode == 0, result.stderr
    assert index.read_text() == original
    expected = "# Topic\n\nIntro stays.\n\n## Notes\n\n- [[wiki/topic/child/index|Child]] — children\n- [[wiki/topic/alpha]] — first\n- [[zeta]] — last\n\n## Related\n\nRelated prose stays.\n- [[wiki/elsewhere]] — related\n"
    assert result.stdout == expected
    applied = run_garden("index", tmp_path, "wiki/topic/index.md", "--apply", input_text=plan)
    assert applied.returncode == 0, applied.stderr
    assert index.read_text() == expected
    # A second run does not duplicate or reorder unrelated entries.
    again = run_garden("index", tmp_path, "wiki/topic/index.md", input_text=plan)
    assert again.stdout == expected


def test_index_editor_refuses_ambiguous_section_and_missing_target(tmp_path: Path) -> None:
    folder = tmp_path / "wiki"
    folder.mkdir()
    index = folder / "index.md"
    original = "# Wiki\n\n## Same\n\n## Same\n"
    index.write_text(original)
    result = run_garden(
        "index", tmp_path, "wiki/index.md", "--apply", input_text='{"section":"Same","entries":[]}'
    )
    assert result.returncode != 0
    assert index.read_text() == original
    result = run_garden(
        "index",
        tmp_path,
        "wiki/index.md",
        "--apply",
        input_text='{"entries":[{"target":"wiki/missing","description":"missing"}]}',
    )
    assert result.returncode != 0
    assert index.read_text() == original


def test_index_editor_creates_child_before_parent_and_accepts_dotted_notes(tmp_path: Path) -> None:
    folder = tmp_path / "wiki" / "topic"
    (folder / "child").mkdir(parents=True)
    (folder / "child" / "example.app.md").write_text("# Note\n")
    child_plan = '{"title":"Child","entries":[{"target":"example.app","description":"dotted note"}]}'
    child = run_garden("index", tmp_path, "wiki/topic/child/index.md", "--apply", input_text=child_plan)
    assert child.returncode == 0, child.stderr
    parent = run_garden(
        "index",
        tmp_path,
        "wiki/topic/index.md",
        "--apply",
        input_text='{"title":"Topic","entries":[{"target":"child/index","description":"children"}]}',
    )
    assert parent.returncode == 0, parent.stderr
    assert (folder / "index.md").read_text() == "# Topic\n\n- [[child/index]] — children\n"


@pytest.mark.parametrize("relative", ["wiki/_sources/index.md", "wiki/.hidden/index.md", "wiki/../index.md"])
def test_index_editor_refuses_protected_paths_even_during_preview(tmp_path: Path, relative: str) -> None:
    (tmp_path / "wiki").mkdir()
    result = run_garden("index", tmp_path, relative, input_text='{"title":"Bad","entries":[]}')
    assert result.returncode != 0
    assert not (tmp_path / relative).exists()


@pytest.mark.parametrize(
    "body",
    ["- [[note]] — note\n  continuation stays with note\n", "```markdown\n- [[note]] — example\n```\n"],
)
def test_index_editor_refuses_complex_entry_blocks(tmp_path: Path, body: str) -> None:
    (tmp_path / "wiki").mkdir()
    index = tmp_path / "wiki" / "index.md"
    original = "# Wiki\n\n" + body
    index.write_text(original)
    (tmp_path / "wiki" / "note.md").write_text("# Note\n")
    result = run_garden(
        "index",
        tmp_path,
        "wiki/index.md",
        "--apply",
        input_text='{"entries":[{"target":"note","description":"changed"}]}',
    )
    assert result.returncode != 0
    assert index.read_text() == original


def test_questions_renderer_preserves_header_and_empty_report(tmp_path: Path) -> None:
    (tmp_path / "wiki").mkdir()
    source = tmp_path / "wiki" / "note.md"
    source.write_text('# Note\n\n> [!question]\n> A "quote" and \\path?\n')
    (tmp_path / "wiki" / "old.sync-conflict-20260101-120000-host.md").write_text(
        "> [!question]\n> Conflict\n"
    )
    report = tmp_path / "Utility" / "obsidian-knowledge" / "reports" / "open-questions.md"
    report.parent.mkdir(parents=True)
    header = "---\ncreated: untouched\n---\n# Open questions\n\n> Regenerated; do not edit.\n\n**Last run:** old\n\n## Scope\n\nOnly managed notes.\n\n"
    original = header + '- [[wiki/old]] — line 9 — "Old"\n'
    report.write_text(original)
    args = (
        "--report",
        "Utility/obsidian-knowledge/reports/open-questions.md",
        "--timestamp",
        "2026-10-03T12:00:00-07:00",
    )
    result = run_garden("questions", tmp_path, *args)
    assert result.returncode == 0, result.stderr
    expected = (
        header.replace("**Last run:** old", "**Last run:** 2026-10-03T12:00:00-07:00")
        + '- [[wiki/note]] — line 3 — "A \\"quote\\" and \\path?"\n'
    )
    assert result.stdout == expected
    assert report.read_text() == original
    applied = run_garden("questions", tmp_path, *args, "--apply")
    assert applied.returncode == 0, applied.stderr
    assert report.read_text() == expected
    source.write_text("# Resolved\n")
    empty = run_garden("questions", tmp_path, *args, "--apply")
    assert empty.returncode == 0, empty.stderr
    assert "[[" not in report.read_text()
    source.write_text("> [!question]\n> Again?\n")
    again = run_garden("questions", tmp_path, *args)
    assert again.returncode == 0, again.stderr
    assert "Only managed notes." in again.stdout
    assert '[[wiki/note]] — line 1 — "Again?"' in again.stdout


@pytest.mark.parametrize(
    "script",
    [
        "audit",
        "links",
        "questions",
    ],
)
def test_scanners_default_to_configured_vault(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, script: str
) -> None:
    vault = tmp_path / "vault"
    (vault / "records").mkdir(parents=True)
    (vault / ".claude").mkdir()
    (vault / ".claude/obsidian-knowledge.yaml").write_text("ai_managed: [records]\n")
    (vault / "records/Default Note.md").write_text("# Note\n")
    (vault / "records/source.md").write_text(
        "# Source\n[[default_note.md]]\n> [!question]\n> Defaults select this vault.\n"
    )
    registry = tmp_path / "vaults.yaml"
    registry.write_text(f"vaults:\n  - {vault}\n")
    monkeypatch.setenv("OBSIDIAN_KNOWLEDGE_VAULTS_CONFIG", str(registry))
    items = json.dumps([{"link": "default_note.md", "sources": "records/source.md", "count": "1"}])
    result = subprocess.run(
        [sys.executable, "-m", "lib.vault_index.cli", "garden", script],
        cwd=tmp_path,
        input=items,
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr
    expected = {
        "audit": f"MISSING_INDEX\t{vault / 'records'}",
        "links": "records/Default Note.md",
        "questions": "records/source.md\t3\tDefaults select this vault.",
    }
    assert expected[script] in result.stdout
    assert not (tmp_path / "wiki").exists()


def test_defaults_choose_first_registered_vault_then_containing_vault(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first, second = tmp_path / "first", tmp_path / "second"
    for vault in (first, second):
        (vault / "wiki").mkdir(parents=True)
    registry = tmp_path / "vaults.yaml"
    registry.write_text(f"vaults:\n  - {first}\n  - {second}\n")
    monkeypatch.setenv("OBSIDIAN_KNOWLEDGE_VAULTS_CONFIG", str(registry))
    command = [sys.executable, "-m", "lib.vault_index.cli", "garden", "index", "wiki/index.md", "--apply"]
    default = subprocess.run(
        command,
        cwd=tmp_path,
        input='{"title":"First","entries":[]}',
        text=True,
        capture_output=True,
        env={**os.environ, "PYTHONPATH": str(ROOT)},
    )
    assert default.returncode == 0, default.stderr
    assert (first / "wiki/index.md").read_text() == "# First\n\n"
    assert not (second / "wiki/index.md").exists()
    selected = subprocess.run(
        command,
        cwd=second / "wiki",
        input='{"title":"Second","entries":[]}',
        text=True,
        capture_output=True,
        env={**os.environ, "PYTHONPATH": str(ROOT)},
    )
    assert selected.returncode == 0, selected.stderr
    assert (second / "wiki/index.md").read_text() == "# Second\n\n"
    assert (first / "wiki/index.md").read_text() == "# First\n\n"


def test_report_apply_uses_default_destination(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "wiki").mkdir()
    (tmp_path / "wiki/note.md").write_text("> [!question]\n> What now?\n")
    registry = tmp_path / "vaults.yaml"
    registry.write_text(f"vaults: [{tmp_path}]\n")
    monkeypatch.setenv("OBSIDIAN_KNOWLEDGE_VAULTS_CONFIG", str(registry))
    result = subprocess.run(
        [sys.executable, "-m", "lib.vault_index.cli", "garden", "questions", "--apply"],
        input="",
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr
    report = tmp_path / "Utility/obsidian-knowledge/reports/open-questions.md"
    assert '[[wiki/note]] — line 1 — "What now?"' in report.read_text()
