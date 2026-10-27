"""Creation-date repairs require explicit evidence and an unchanged reviewed note."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from scripts.backfill_created import (
    Candidate,
    CreationDate,
    Evidence,
    EvidenceFile,
    Plan,
    ScanOptions,
    apply_plan,
    main,
    make_plan,
    recover_history,
)

ROOT = Path(__file__).parents[1]


@pytest.fixture
def vault(tmp_path):
    root = tmp_path / "vault"
    (root / "wiki").mkdir(parents=True)
    Path(os.environ["OBSIDIAN_KNOWLEDGE_CONFIG"]).write_text(
        "ai_managed: [wiki]\nai_assisted: [Inbox, scaffolds]\n"
        "ai_readonly_folders: [wiki/readonly]\nai_readonly_root_files: [private.md]\n"
        "note_creation:\n  template: scaffolds/base.md\n  exclude: [scaffolds]\n"
    )
    return root


def test_plan_preserves_existing_and_leaves_unsourced_dates_unresolved(vault):
    (vault / "wiki/existing.md").write_text("---\ncreated: 2020-01-01\n---\n# Existing")
    (vault / "wiki/empty.md").write_text("---\ncreated:\n---\n# Empty but explicit")
    missing = vault / "wiki/2020-01-01.md"
    missing.write_text("# No proof of creation date")
    before = missing.read_bytes()
    plan = make_plan(vault, ScanOptions())
    assert plan.existing == 2
    assert not plan.candidates
    assert plan.unresolved[0].path == "wiki/2020-01-01.md"
    assert "no explicit" in plan.unresolved[0].reason
    assert missing.read_bytes() == before


def test_metadata_aliases_are_used_only_when_explicitly_trusted(vault):
    note = vault / "wiki/note.md"
    note.write_text("---\ncreated_at: 2020-01-01T01:00:00-08:00\nupdated: 2024-01-01\n---\n# Body")
    assert not make_plan(vault, ScanOptions()).candidates
    plan = make_plan(vault, ScanOptions(source_fields=("created_at",)))
    assert len(plan.candidates) == 1
    assert plan.candidates[0].created.root.isoformat() == "2020-01-01T01:00:00-08:00"
    assert plan.candidates[0].source == "frontmatter:created_at"
    assert plan.candidates[0].sha256 == hashlib.sha256(note.read_bytes()).hexdigest()


@pytest.mark.parametrize("newline,bom", [("\n", b""), ("\r\n", b"\xef\xbb\xbf")])
def test_apply_preserves_formatting_modification_metadata_and_permissions(vault, newline, bom):
    note = vault / "wiki/note.md"
    content = (
        bom
        + newline.join(
            [
                "---",
                "# keep",
                'created_at: "2020-01-01"',
                "updated: 2024-01-01",
                "modified: original",
                "...",
                "# Body",
                "",
            ]
        ).encode()
    )
    note.write_bytes(content)
    note.chmod(0o640)
    plan = make_plan(vault, ScanOptions(source_fields=("created_at",)))
    result = apply_plan(vault, plan)
    assert result.applied == ("wiki/note.md",)
    written = note.read_bytes()
    assert written.startswith(bom + f'---{newline}created: "2020-01-01"{newline}'.encode())
    assert written.endswith(content[len(bom + f"---{newline}".encode()) :])
    assert stat.S_IMODE(note.stat().st_mode) == 0o640
    assert apply_plan(vault, plan).already_present == ("wiki/note.md",)


def test_external_evidence_can_repair_a_note_without_frontmatter(vault):
    note = vault / "wiki/note.md"
    note.write_text("# Body\n")
    evidence = EvidenceFile(
        records=(Evidence(path="wiki/note.md", created="2020-01-01", source="verified backup"),)
    )
    plan = make_plan(vault, ScanOptions(evidence=evidence))
    apply_plan(vault, plan)
    assert note.read_text() == '---\ncreated: "2020-01-01"\n---\n\n# Body\n'


def test_conflicting_and_invalid_evidence_is_not_proposed(vault):
    (vault / "wiki/conflict.md").write_text("---\nfirst: 2020-01-01\nsecond: 2021-01-01\n---\n# Body")
    (vault / "wiki/invalid.md").write_text("---\nfirst: yesterday\n---\n# Body")
    plan = make_plan(vault, ScanOptions(source_fields=("first", "second")))
    assert not plan.candidates
    assert len(plan.unresolved) == 2


def test_matching_evidence_sources_are_combined(vault):
    (vault / "wiki/note.md").write_text("---\nfirst: 2020-01-01\nsecond: 2020-01-01\n---\n# Body")
    plan = make_plan(vault, ScanOptions(source_fields=("first", "second")))
    assert plan.candidates[0].source == "frontmatter:first; frontmatter:second"


@pytest.mark.parametrize("value", [True, 1234, "yesterday", "", "2099-01-01"])
def test_creation_evidence_rejects_guesses_and_future_dates(value):
    with pytest.raises(ValueError):
        CreationDate.model_validate(value)


def test_future_datetime_is_rejected_and_naive_dates_are_preserved():
    with pytest.raises(ValueError):
        CreationDate.model_validate(datetime.now(UTC) + timedelta(days=1))
    value = datetime(2020, 1, 1, 1, 2, 3, tzinfo=UTC).replace(tzinfo=None)
    assert CreationDate.model_validate(value).root == value


def test_unsafe_unmanaged_excluded_and_published_notes_are_not_repaired(vault, tmp_path):
    for name in ("wiki/_sources", "wiki/readonly", "scaffolds", ".hidden", "Other", "Inbox"):
        folder = vault / name
        folder.mkdir(parents=True)
        (folder / "note.md").write_text("---\ncreated_at: 2020-01-01\n---\n# Body")
    outside = tmp_path / "outside.md"
    outside.write_text("# Outside")
    (vault / "wiki/link.md").symlink_to(outside)
    (vault / "wiki/published.md").write_text("---\ndg-publish: true\ncreated_at: 2020-01-01\n---\n# Body")
    (vault / "private.md").write_text("# Private")
    (vault / "wiki/bad.md").write_text("---\n[bad: yaml\n---\n# Body")
    (vault / "wiki/unclosed.md").write_text("---\n# Body")
    (vault / "wiki/raw.bin").write_bytes(b"\xff")
    plan = make_plan(vault, ScanOptions(source_fields=("created_at",)))
    assert {item.path for item in plan.candidates} == {"Inbox/note.md"}
    assert plan.excluded == 4
    assert len(plan.unresolved) == 3
    assert outside.read_text() == "# Outside"


def test_changed_note_aborts_preflight_before_any_writes(vault):
    first = vault / "wiki/a.md"
    second = vault / "wiki/b.md"
    for note in (first, second):
        note.write_text("---\ncreated_at: 2020-01-01\n---\n# Body")
    original = first.read_bytes()
    plan = make_plan(vault, ScanOptions(source_fields=("created_at",)))
    second.write_text("# User edit after review")
    with pytest.raises(ValueError, match="changed since review"):
        apply_plan(vault, plan)
    assert first.read_bytes() == original
    assert second.read_text() == "# User edit after review"


def test_newly_supplied_created_value_is_never_overwritten(vault):
    note = vault / "wiki/note.md"
    note.write_text("---\ncreated_at: 2020-01-01\n---\n# Body")
    plan = make_plan(vault, ScanOptions(source_fields=("created_at",)))
    note.write_text("---\ncreated: 1999-01-01\n---\n# User edit")
    before = note.read_bytes()
    assert apply_plan(vault, plan).already_present == ("wiki/note.md",)
    assert note.read_bytes() == before


def test_apply_rechecks_policy_and_plan_vault(vault, tmp_path):
    (vault / "wiki/note.md").write_text("---\ncreated_at: 2020-01-01\n---\n# Body")
    plan = make_plan(vault, ScanOptions(source_fields=("created_at",)))
    with pytest.raises(ValueError, match="different vault"):
        apply_plan(tmp_path, plan)
    Path(os.environ["OBSIDIAN_KNOWLEDGE_CONFIG"]).write_text(
        "ai_managed: [wiki]\nai_readonly_folders: [wiki]\n"
    )
    with pytest.raises(ValueError, match="read-only"):
        apply_plan(vault, plan)


def test_duplicate_and_traversal_plan_paths_are_rejected(vault):
    candidate = Candidate(path="../outside.md", created="2020-01-01", source="verified", sha256="0" * 64)
    with pytest.raises(ValidationError, match="duplicate"):
        Plan(vault=vault, candidates=(candidate, candidate), unresolved=(), existing=0, excluded=0)
    plan = Plan(vault=vault, candidates=(candidate,), unresolved=(), existing=0, excluded=0)
    with pytest.raises(ValueError, match="visible vault path"):
        apply_plan(vault, plan)


def test_path_selection_and_missing_paths(vault):
    for name in ("a.md", "b.md"):
        (vault / "wiki" / name).write_text("---\ncreated_at: 2020-01-01\n---\n# Body")
    plan = make_plan(vault, ScanOptions(source_fields=("created_at",), paths=(Path("wiki/a.md"),)))
    assert len(plan.candidates) == 1
    with pytest.raises(ValueError, match="does not exist"):
        make_plan(vault, ScanOptions(paths=(Path("wiki/missing.md"),)))


def test_cli_defaults_to_private_plan_and_requires_explicit_apply(vault, tmp_path, capsys):
    note = vault / "wiki/note.md"
    note.write_text("---\ncreated_at: 2020-01-01\n---\n# Body")
    baseline = note.read_bytes()
    plan = tmp_path / "review.json"
    assert main(["--vault", str(vault), "--plan", str(plan), "--source-field", "created_at"]) == 0
    assert note.read_bytes() == baseline
    assert stat.S_IMODE(plan.stat().st_mode) == 0o600
    assert "vault has not been changed" in capsys.readouterr().out
    assert main(["apply", "--vault", str(vault), "--plan", str(plan)]) == 0
    assert json.loads(capsys.readouterr().out)["applied"] == ["wiki/note.md"]


def test_cli_supports_vetted_evidence_and_refuses_to_overwrite_plan(vault, tmp_path):
    (vault / "wiki/note.md").write_text("# Body")
    evidence = tmp_path / "evidence.json"
    evidence.write_text(
        '{"records":[{"path":"wiki/note.md","created":"2020-01-01","source":"verified backup"}]}'
    )
    plan = tmp_path / "review.json"
    args = ["--vault", str(vault), "--plan", str(plan), "--evidence", str(evidence)]
    main(args)
    assert len(Plan.model_validate_json(plan.read_text()).candidates) == 1
    before = plan.read_bytes()
    with pytest.raises(SystemExit):
        main(args)
    assert plan.read_bytes() == before
    with pytest.raises(SystemExit):
        main(["apply", "--vault", str(vault), "--plan", str(plan), "--evidence", str(evidence)])


def test_cli_refuses_plans_inside_vault(vault):
    with pytest.raises(SystemExit):
        main(["--vault", str(vault), "--plan", str(vault / "wiki/review.json")])


def test_script_runs_from_outside_repository(vault, tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/backfill_created.py"),
            "--vault",
            str(vault),
            "--plan",
            str(tmp_path / "review.json"),
        ],
        cwd=tmp_path,
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr


def test_history_recovers_actual_metadata_not_the_version_filename_date(vault, tmp_path):
    (vault / "wiki/note.md").write_text("# Same body\n")
    history = tmp_path / "versions"
    (history / "wiki").mkdir(parents=True)
    (history / "wiki/note~20251230-120000.md").write_text("---\ncreated: 2020-01-01\n---\n# Same body\n")
    original = make_plan(vault, ScanOptions())
    found = recover_history(vault, history, original)
    assert found.records[0].created.root.isoformat() == "2020-01-01"
    assert not found.records[0].requires_review
    plan = make_plan(vault, ScanOptions(evidence=found))
    assert apply_plan(vault, plan).applied == ("wiki/note.md",)


def test_changed_historical_body_requires_review_and_is_never_auto_applied(vault, tmp_path):
    note = vault / "wiki/note.md"
    note.write_text("# Current body\n")
    history = tmp_path / "versions"
    (history / "wiki").mkdir(parents=True)
    (history / "wiki/note.md").write_text("---\ncreated: 2020-01-01\n---\n# Older body\n")
    found = recover_history(vault, history, make_plan(vault, ScanOptions()))
    assert found.records[0].requires_review
    plan = make_plan(vault, ScanOptions(evidence=found))
    result = apply_plan(vault, plan)
    assert result.applied == ()
    assert result.pending_review == ("wiki/note.md",)
    assert note.read_text() == "# Current body\n"


def test_conflicting_history_stays_unresolved_even_with_a_trusted_record(vault, tmp_path):
    (vault / "wiki/note.md").write_text("# Body\n")
    history = tmp_path / "versions"
    (history / "wiki").mkdir(parents=True)
    (history / "wiki/note~20240101-000000.md").write_text("---\ncreated: 2020-01-01\n---\n# Body\n")
    trusted = EvidenceFile(
        records=(Evidence(path="wiki/note.md", created="2021-01-01", source="creation log"),)
    )
    original = make_plan(vault, ScanOptions(evidence=trusted))
    found = recover_history(vault, history, original)
    combined = EvidenceFile(records=(*trusted.records, *found.records))
    plan = make_plan(vault, ScanOptions(evidence=combined))
    assert not plan.candidates
    assert len(plan.unresolved) == 1


def test_history_discovery_rejects_stale_body_hash(vault, tmp_path):
    note = vault / "wiki/note.md"
    note.write_text("# Body\n")
    history = tmp_path / "versions"
    (history / "wiki").mkdir(parents=True)
    (history / "wiki/note.md").write_text("---\ncreated: 2020-01-01\n---\n# Body\n")
    found = recover_history(vault, history, make_plan(vault, ScanOptions()))
    note.write_text("# Changed during discovery\n")
    plan = make_plan(vault, ScanOptions(evidence=found))
    assert not plan.candidates
    assert len(plan.unresolved) == 1


def test_history_skips_conflicts_symlinks_bad_yaml_and_missing_metadata(vault, tmp_path):
    (vault / "wiki/note.md").write_text("# Body\n")
    history = tmp_path / "versions"
    (history / "wiki").mkdir(parents=True)
    (history / "wiki/note.md").write_text("# Body\n")
    (history / "wiki/note~20240101-000000.md").write_text("---\n[bad YAML\n---\n")
    (history / "wiki/note~20240101-010000.md").symlink_to(vault / "wiki/note.md")
    (history / "wiki/note.sync-conflict-example.md").write_text("---\ncreated: 2020-01-01\n---\n# Body\n")
    plan = make_plan(vault, ScanOptions())
    assert not recover_history(vault, history, plan).records
    with pytest.raises(ValueError, match="not a directory"):
        recover_history(vault, tmp_path / "missing", plan)


def test_cli_discovers_history_but_leaves_changed_bodies_pending(vault, tmp_path, capsys):
    (vault / "wiki/note.md").write_text("# Current body\n")
    history = tmp_path / "versions"
    (history / "wiki").mkdir(parents=True)
    (history / "wiki/note.md").write_text("---\ncreated: 2020-01-01\n---\n# Older body\n")
    plan = tmp_path / "review.json"
    main(["--vault", str(vault), "--plan", str(plan), "--syncthing-history", str(history)])
    assert "1 require review" in capsys.readouterr().out
    main(["apply", "--vault", str(vault), "--plan", str(plan)])
    assert json.loads(capsys.readouterr().out)["pending_review"] == ["wiki/note.md"]
