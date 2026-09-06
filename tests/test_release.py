"""Release version selection and manifest synchronization."""

from __future__ import annotations

import json
import subprocess
import tomllib
from pathlib import Path

import pytest

from scripts.prepare_release import prepare_version, release_state


@pytest.mark.parametrize(
    ("current", "published", "expected"),
    [
        ("3.22.36", ["3.21.0"], "3.22.36"),
        ("3.22.36", ["3.22.36"], "3.22.37"),
        ("3.22.9", ["3.22.10"], "3.22.11"),
        ("4.0.0", ["3.22.36"], "4.0.0"),
        ("3.22.36", [], "3.22.36"),
    ],
)
def test_prepare_version_syncs_manifests(tmp_path: Path, current, published, expected):
    (tmp_path / "pyproject.toml").write_text(
        f'[project]\nname = "obsidian-knowledge"\nversion = "{current}"\n'
    )
    (tmp_path / "plugin.yaml").write_text("name: obsidian-knowledge\nversion: 3.22.34\n")
    for name in (".codex-plugin/plugin.json", ".claude-plugin/plugin.json"):
        path = tmp_path / name
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps({"name": "obsidian-knowledge", "version": "3.22.34"}))
    marketplace = tmp_path / ".claude-plugin/marketplace.json"
    marketplace.write_text(json.dumps({"plugins": [{"name": "obsidian-knowledge", "version": "3.22.34"}]}))

    assert prepare_version(tmp_path, published) == expected
    assert tomllib.loads((tmp_path / "pyproject.toml").read_text())["project"]["version"] == expected
    assert f"version: {expected}\n" in (tmp_path / "plugin.yaml").read_text()
    for name in (".codex-plugin/plugin.json", ".claude-plugin/plugin.json"):
        assert json.loads((tmp_path / name).read_text())["version"] == expected
    assert json.loads(marketplace.read_text())["plugins"][0]["version"] == expected


def test_release_retries_reuse_commit_and_stale_runs_skip(tmp_path: Path):
    def git(*args):
        return subprocess.check_output(["git", "-C", str(tmp_path), *args], text=True).strip()

    git("init", "-b", "main")
    git("config", "user.name", "Release test")
    git("config", "user.email", "test@example.com")
    git("commit", "--allow-empty", "-m", "Source change")
    source = git("rev-parse", "HEAD")
    assert release_state(tmp_path, source) == "new"
    git("commit", "--allow-empty", "-m", "Release 3.22.37", "-m", f"Source-Commit: {source}")
    assert release_state(tmp_path, source) == "retry"
    git("commit", "--allow-empty", "-m", "Next source change")
    assert release_state(tmp_path, source) == "stale"
