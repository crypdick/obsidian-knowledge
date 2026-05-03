"""Subprocess tests for hooks/enforce-conventions.py."""

import json
import subprocess
from pathlib import Path

HOOK = Path(__file__).parent.parent / "hooks" / "enforce-conventions.py"


def run_hook(payload: dict, env: dict | None = None) -> tuple[int, str, str]:
    proc = subprocess.run(
        ["python3", str(HOOK)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
    )
    return proc.returncode, proc.stdout, proc.stderr


def test_silent_outside_vault(tmp_path, subprocess_vault):
    _, env = subprocess_vault
    note = tmp_path / "outside.md"
    payload = {
        "tool_name": "Write",
        "tool_input": {"file_path": str(note), "content": "[[foo.md]]"},
    }
    rc, out, _ = run_hook(payload, env=env)
    assert rc == 0
    assert out == ""


def test_rejects_md_wikilink_in_vault(subprocess_vault):
    vault, env = subprocess_vault
    note = vault / "note.md"
    payload = {
        "tool_name": "Write",
        "tool_input": {"file_path": str(note), "content": "See [[foo.md]]."},
    }
    rc, out, _ = run_hook(payload, env=env)
    assert rc == 0
    assert "BLOCKED" in out or "deny" in out
    assert "[[foo.md]]" in out


def test_allows_non_md_wikilink(subprocess_vault):
    vault, env = subprocess_vault
    note = vault / "note.md"
    payload = {
        "tool_name": "Write",
        "tool_input": {"file_path": str(note), "content": "See [[photo.jpg]]."},
    }
    _, out, _ = run_hook(payload, env=env)
    assert out == ""


def test_rejects_undated_file_in_journal(subprocess_vault):
    vault, env = subprocess_vault
    (vault / "Journal").mkdir()
    note = vault / "Journal" / "untitled.md"
    payload = {
        "tool_name": "Write",
        "tool_input": {"file_path": str(note), "content": "hi"},
    }
    _, out, _ = run_hook(payload, env=env)
    assert "BLOCKED" in out or "deny" in out
    assert "date" in out.lower() or "prefix" in out.lower()


def test_allows_dated_file_in_journal(subprocess_vault):
    vault, env = subprocess_vault
    (vault / "Journal").mkdir()
    note = vault / "Journal" / "2026-04-21 foo.md"
    payload = {
        "tool_name": "Write",
        "tool_input": {"file_path": str(note), "content": "hi"},
    }
    _, out, _ = run_hook(payload, env=env)
    assert out == ""


def test_allows_index_md_without_date_prefix(subprocess_vault):
    vault, env = subprocess_vault
    (vault / "wiki" / "foo" / "plans").mkdir(parents=True)
    note = vault / "wiki" / "foo" / "plans" / "index.md"
    payload = {
        "tool_name": "Write",
        "tool_input": {"file_path": str(note), "content": "# Plans"},
    }
    _, out, _ = run_hook(payload, env=env)
    assert out == ""


def test_skips_date_check_on_edit_of_existing_file(subprocess_vault):
    vault, env = subprocess_vault
    (vault / "Journal").mkdir()
    note = vault / "Journal" / "legacy-name.md"
    note.write_text("existing")
    payload = {
        "tool_name": "Edit",
        "tool_input": {
            "file_path": str(note),
            "old_string": "existing",
            "new_string": "updated",
        },
    }
    _, out, _ = run_hook(payload, env=env)
    assert out == ""


def test_rejects_malformed_frontmatter(subprocess_vault):
    vault, env = subprocess_vault
    note = vault / "note.md"
    payload = {
        "tool_name": "Write",
        "tool_input": {
            "file_path": str(note),
            "content": "---\ntitle: [unclosed\n---\n\nbody",
        },
    }
    _, out, _ = run_hook(payload, env=env)
    assert "BLOCKED" in out or "deny" in out
    assert "frontmatter" in out.lower() or "yaml" in out.lower()


def test_accepts_valid_frontmatter(subprocess_vault):
    vault, env = subprocess_vault
    note = vault / "note.md"
    payload = {
        "tool_name": "Write",
        "tool_input": {
            "file_path": str(note),
            "content": "---\ntitle: foo\n---\n\nbody",
        },
    }
    _, out, _ = run_hook(payload, env=env)
    assert out == ""


def test_accepts_empty_frontmatter(subprocess_vault):
    vault, env = subprocess_vault
    note = vault / "note.md"
    payload = {
        "tool_name": "Write",
        "tool_input": {
            "file_path": str(note),
            "content": "---\n---\n\nbody",
        },
    }
    _, out, _ = run_hook(payload, env=env)
    assert out == ""
