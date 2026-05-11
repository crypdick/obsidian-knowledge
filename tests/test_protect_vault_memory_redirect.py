"""Integration test: protect-vault.py block_memory_file_creation cites
the resolved per-repo vault path in the deny message.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
HOOK = PLUGIN_ROOT / "hooks" / "protect-vault.py"


def _run_hook(payload: dict, cwd: Path, env: dict) -> tuple[int, str, str]:
    proc = subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        cwd=str(cwd),
        env=env,
    )
    return proc.returncode, proc.stdout, proc.stderr


@pytest.fixture
def repo_with_remote(tmp_path):
    """A git repo with a github remote, ready to use as cwd."""
    repo = tmp_path / "myrepo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "remote", "add", "origin",
         "git@github.com:Anthropic/claude-code.git"],
        check=True,
    )
    return repo


def test_redirect_cites_repo_path(tmp_path, repo_with_remote, subprocess_vault):
    vault, env = subprocess_vault
    blocked_target = (
        tmp_path / ".claude" / "projects" / "-some-slug" / "memory" / "feedback_x.md"
    )
    blocked_target.parent.mkdir(parents=True)

    payload = {
        "tool_name": "Write",
        "tool_input": {
            "file_path": str(blocked_target),
            "content": "...",
        },
    }
    rc, stdout, _ = _run_hook(payload, cwd=repo_with_remote, env=env)
    assert rc == 0
    out = json.loads(stdout)
    reason = out["hookSpecificOutput"]["permissionDecisionReason"]
    # Cites the resolved per-repo target path
    assert "BLOCKED [wiki-policy]" in reason
    assert "repos/Anthropic/claude-code/memory/feedback_x.md" in reason
    assert "Anthropic/claude-code" in reason


def test_redirect_cites_host_path_when_no_repo(tmp_path, subprocess_vault):
    vault, env = subprocess_vault
    non_repo = tmp_path / "not-a-repo"
    non_repo.mkdir()

    blocked_target = (
        tmp_path / ".claude" / "projects" / "-some-slug" / "memory" / "project_x.md"
    )
    blocked_target.parent.mkdir(parents=True)

    payload = {
        "tool_name": "Write",
        "tool_input": {
            "file_path": str(blocked_target),
            "content": "...",
        },
    }
    rc, stdout, _ = _run_hook(payload, cwd=non_repo, env=env)
    assert rc == 0
    out = json.loads(stdout)
    reason = out["hookSpecificOutput"]["permissionDecisionReason"]
    assert "systems/machines/" in reason
    assert "memory/project_x.md" in reason


def test_user_prefix_files_are_not_blocked(tmp_path, subprocess_vault):
    """user_*.md files (user-profile facts) stay in ~/.claude — only feedback/project/reference are blocked."""
    vault, env = subprocess_vault
    target = (
        tmp_path / ".claude" / "projects" / "-slug" / "memory" / "user_profile.md"
    )
    target.parent.mkdir(parents=True)
    payload = {
        "tool_name": "Write",
        "tool_input": {"file_path": str(target), "content": "..."},
    }
    rc, stdout, _ = _run_hook(payload, cwd=tmp_path, env=env)
    # Should pass through (no JSON deny output, exit 0 with empty stdout)
    assert rc == 0
    assert stdout.strip() == ""
