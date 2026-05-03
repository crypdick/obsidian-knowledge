"""Subprocess tests for hooks/nudge-index-sync.py."""

import json
import os
import subprocess
import uuid
from pathlib import Path

HOOK = Path(__file__).parent.parent / "hooks" / "nudge-index-sync.py"
FIXTURES = Path(__file__).parent / "fixtures"
RUN_ID = f"{os.getpid()}-{uuid.uuid4().hex[:8]}"


def run_hook(payload: dict, cwd: str, env: dict) -> tuple[int, str]:
    proc = subprocess.run(
        ["python3", str(HOOK)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        cwd=cwd,
        env=env,
    )
    return proc.returncode, proc.stdout


def test_silent_outside_vault(tmp_path, subprocess_vault):
    _, env = subprocess_vault
    payload = {
        "session_id": f"s-{RUN_ID}-novault",
        "stop_hook_active": False,
        "transcript_path": str(FIXTURES / "transcript_new_file_no_index.jsonl"),
    }
    _, out = run_hook(payload, cwd=str(tmp_path), env=env)
    assert out == ""


def test_fires_when_new_file_no_index_edit(subprocess_vault):
    vault, env = subprocess_vault
    payload = {
        "session_id": f"s-{RUN_ID}-fires",
        "stop_hook_active": False,
        "transcript_path": str(FIXTURES / "transcript_new_file_no_index.jsonl"),
    }
    _, out = run_hook(payload, cwd=str(vault), env=env)
    assert "block" in out
    assert "index.md" in out


def test_silent_when_index_was_edited(subprocess_vault):
    vault, env = subprocess_vault
    payload = {
        "session_id": f"s-{RUN_ID}-indexed",
        "stop_hook_active": False,
        "transcript_path": str(FIXTURES / "transcript_new_file_with_index.jsonl"),
    }
    _, out = run_hook(payload, cwd=str(vault), env=env)
    assert out == ""


def test_silent_when_stop_hook_active(subprocess_vault):
    vault, env = subprocess_vault
    payload = {
        "session_id": f"s-{RUN_ID}-active",
        "stop_hook_active": True,
        "transcript_path": str(FIXTURES / "transcript_new_file_no_index.jsonl"),
    }
    _, out = run_hook(payload, cwd=str(vault), env=env)
    assert out == ""
