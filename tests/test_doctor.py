"""Subprocess tests for hooks/doctor.py."""

import json
import os
import subprocess
import uuid
from pathlib import Path

HOOK = Path(__file__).parent.parent / "hooks" / "doctor.py"

# Unique per-process so the session-keyed debounce marker never collides
# with a prior test run.
RUN_ID = f"{os.getpid()}-{uuid.uuid4().hex[:8]}"


def run_hook(cwd: str, env: dict | None = None, payload: dict | None = None) -> str:
    proc = subprocess.run(
        ["python3", str(HOOK)],
        input=json.dumps(payload or {}),
        capture_output=True,
        text=True,
        cwd=cwd,
        env=env,
    )
    return proc.stdout


def test_silent_outside_vault(tmp_path, subprocess_vault):
    _, env = subprocess_vault
    out = run_hook(str(tmp_path), env=env)
    assert out == ""


def test_silent_clean_vault(subprocess_vault):
    vault, env = subprocess_vault
    out = run_hook(str(vault), env=env)
    assert out == ""


def test_counts_wikilink_violations(subprocess_vault):
    vault, env = subprocess_vault
    (vault / "note.md").write_text("See [[foo.md]].")
    out = run_hook(str(vault), env=env)
    assert "wikilink-ext" in out


def test_counts_undated_files_in_journal(subprocess_vault):
    vault, env = subprocess_vault
    (vault / "Journal").mkdir()
    (vault / "Journal" / "untitled.md").write_text("hi")
    out = run_hook(str(vault), env=env)
    assert "undated-file" in out


def test_counts_yaml_errors(subprocess_vault):
    vault, env = subprocess_vault
    (vault / "note.md").write_text("---\ntitle: [broken\n---\nbody")
    out = run_hook(str(vault), env=env)
    assert "yaml-err" in out


def test_counts_needs_attention_entries(subprocess_vault):
    vault, env = subprocess_vault
    state_dir = vault / "Utility" / "obsidian-knowledge"
    state_dir.mkdir(parents=True)
    (state_dir / "needs-attention.md").write_text("# Needs Attention\n\n- [ ] foo\n- [ ] bar\n")
    out = run_hook(str(vault), env=env)
    assert "needs-attention" in out
    assert "2" in out


def test_skips_dotfolders(subprocess_vault):
    vault, env = subprocess_vault
    (vault / ".trash").mkdir()
    (vault / ".trash" / "junk.md").write_text("See [[foo.md]].")
    out = run_hook(str(vault), env=env)
    assert out == ""


def test_skips_sources_folders(subprocess_vault):
    vault, env = subprocess_vault
    (vault / "wiki" / "_sources").mkdir(parents=True)
    (vault / "wiki" / "_sources" / "orig.md").write_text("See [[foo.md]].")
    out = run_hook(str(vault), env=env)
    assert out == ""


def test_debounces_repeat_fire_within_session(subprocess_vault):
    """A SessionStart re-fire for the same session_id skips the re-scan.

    Guards against a compaction loop re-walking the vault and re-printing the
    digest back to back.
    """
    vault, env = subprocess_vault
    (vault / "note.md").write_text("See [[foo.md]].")
    session = {"session_id": f"s-{RUN_ID}-debounce"}

    out1 = run_hook(str(vault), env=env, payload=session)
    out2 = run_hook(str(vault), env=env, payload=session)

    assert "wikilink-ext" in out1
    assert out2 == ""  # second fire debounced → no re-scan output
