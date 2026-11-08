"""Release version selection and manifest synchronization."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

from scripts.prepare_release import prepare_version, release_state


def test_manual_package_bump_passes_checkout_checks_and_syncs_release(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("UV_CACHE_DIR", str(tmp_path / "uv-cache"))
    root = Path(__file__).resolve().parents[1]
    for name in (
        ".claude-plugin/plugin.json",
        ".claude-plugin/marketplace.json",
        ".codex-plugin/plugin.json",
        "plugins/obsidian-knowledge/.codex-plugin/plugin.json",
        "plugins/obsidian-knowledge/skills/obsidian-knowledge/SKILL.md",
        "plugins/obsidian-knowledge/hooks/hooks.json",
        "skills/obsidian-knowledge/SKILL.md",
        "hooks/codex-hooks.json",
        "scripts/sync_codex_plugin.py",
        "tests/test_cli.py",
    ):
        destination = tmp_path / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(root / name, destination)
    published = tomllib.loads((root / "pyproject.toml").read_text())["project"]["version"]
    # Dependency resolution is unrelated to the package/manifest boundary.
    (tmp_path / "pyproject.toml").write_text(
        f'[project]\nname = "obsidian-knowledge"\nversion = "{published}"\n'
        'requires-python = ">=3.12"\ndependencies = []\n'
    )
    versioned = subprocess.run(
        ["uv", "version", "99.0.0", "--no-sync", "--offline"],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
    )
    assert versioned.returncode == 0, versioned.stdout + versioned.stderr
    assert tomllib.loads((tmp_path / "pyproject.toml").read_text())["project"]["version"] == "99.0.0"
    locked = tomllib.loads((tmp_path / "uv.lock").read_text())
    assert (
        next(item["version"] for item in locked["package"] if item["name"] == "obsidian-knowledge")
        == "99.0.0"
    )

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "--noconftest",
            "-o",
            "addopts=",
            "tests/test_cli.py",
            "-k",
            "test_codex_marketplace_points_to_packaged_plugin or test_claude_marketplace_uses_string_local_source",
        ],
        cwd=tmp_path,
        env={**os.environ, "PYTHONPATH": str(root)},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr

    assert prepare_version(tmp_path, [published]) == "99.0.0"
    for name in (".codex-plugin/plugin.json", ".claude-plugin/plugin.json"):
        assert json.loads((tmp_path / name).read_text())["version"] == "99.0.0"
    marketplace = json.loads((tmp_path / ".claude-plugin/marketplace.json").read_text())
    assert marketplace["plugins"][0]["version"] == "99.0.0"
    subprocess.run(
        [sys.executable, "scripts/sync_codex_plugin.py"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    packaged = json.loads((tmp_path / "plugins/obsidian-knowledge/.codex-plugin/plugin.json").read_text())
    assert packaged["version"].split("+", 1)[0] == "99.0.0"


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
    for name in (".codex-plugin/plugin.json", ".claude-plugin/plugin.json"):
        path = tmp_path / name
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps({"name": "obsidian-knowledge", "version": "3.22.34"}))
    marketplace = tmp_path / ".claude-plugin/marketplace.json"
    marketplace.write_text(json.dumps({"plugins": [{"name": "obsidian-knowledge", "version": "3.22.34"}]}))

    assert prepare_version(tmp_path, published) == expected
    assert tomllib.loads((tmp_path / "pyproject.toml").read_text())["project"]["version"] == expected
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


@pytest.mark.parametrize("invalid", ["codex", "claude", "missing", "duplicate"])
def test_prepare_version_rejects_identity_errors_without_writes(tmp_path: Path, invalid: str):
    project = tmp_path / "pyproject.toml"
    project.write_text('[project]\nname = "obsidian-knowledge"\nversion = "1.0.0"\n')
    paths = [project]
    for host in ("codex", "claude"):
        manifest = tmp_path / f".{host}-plugin/plugin.json"
        manifest.parent.mkdir()
        manifest.write_text(
            json.dumps({"name": "other" if host == invalid else "obsidian-knowledge", "version": "1.0.0"})
        )
        paths.append(manifest)
    marketplace = tmp_path / ".claude-plugin/marketplace.json"
    entry = {"name": "obsidian-knowledge", "version": "1.0.0"}
    entries = [] if invalid == "missing" else [entry, entry] if invalid == "duplicate" else [entry]
    marketplace.write_text(json.dumps({"plugins": entries}))
    paths.append(marketplace)
    before = {path: path.read_bytes() for path in paths}

    with pytest.raises(ValueError, match="obsidian-knowledge"):
        prepare_version(tmp_path, ["1.0.0"])

    assert {path: path.read_bytes() for path in paths} == before


def test_prepare_version_preserves_other_marketplace_plugins(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "obsidian-knowledge"\nversion = "2.0.0"\n')
    for host in ("codex", "claude"):
        manifest = tmp_path / f".{host}-plugin/plugin.json"
        manifest.parent.mkdir()
        manifest.write_text(json.dumps({"name": "obsidian-knowledge", "version": "1.0.0"}))
    marketplace = tmp_path / ".claude-plugin/marketplace.json"
    other = {"name": "other", "version": "9.0.0"}
    marketplace.write_text(
        json.dumps({"plugins": [other, {"name": "obsidian-knowledge", "version": "1.0.0"}]})
    )

    assert prepare_version(tmp_path, ["1.0.0"]) == "2.0.0"
    entries = json.loads(marketplace.read_text())["plugins"]
    assert entries == [other, {"name": "obsidian-knowledge", "version": "2.0.0"}]
