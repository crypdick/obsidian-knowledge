"""Tests for hookslib.repo_memory.resolve_target."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from hookslib import repo_memory


# ── URL parsing ───────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "url,expected",
    [
        ("git@github.com:Anthropic/claude-code.git", ("Anthropic", "claude-code")),
        ("https://github.com/Anthropic/claude-code.git", ("Anthropic", "claude-code")),
        ("https://github.com/Anthropic/claude-code", ("Anthropic", "claude-code")),
        ("ssh://git@github.com/Anthropic/claude-code.git", ("Anthropic", "claude-code")),
        ("git@gitlab.com:group/sub/project.git", ("sub", "project")),  # last pair
        ("https://gitlab.com/group/sub/project", ("sub", "project")),
        ("", None),
        ("not-a-url", None),
        ("https://example.com/", None),
    ],
)
def test_parse_remote_url(url, expected):
    assert repo_memory.parse_remote_url(url) == expected


# ── Resolver: repo case ───────────────────────────────────────────────


def _git_init(path: Path, remote: str | None = None) -> None:
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    if remote:
        subprocess.run(
            ["git", "-C", str(path), "remote", "add", "origin", remote],
            check=True,
        )


def test_resolve_target_repo_basic(tmp_path):
    _git_init(tmp_path, "git@github.com:ricdec/obsidian-knowledge.git")
    t = repo_memory.resolve_target(tmp_path)
    assert t.kind == "repo"
    assert t.owner == "ricdec"
    assert t.repo == "obsidian-knowledge"
    assert t.rel_path == "repos/ricdec/obsidian-knowledge/memory"
    assert t.remote_url == "git@github.com:ricdec/obsidian-knowledge.git"


def test_resolve_target_repo_walks_up(tmp_path):
    _git_init(tmp_path, "https://github.com/ricdec/obsidian-knowledge.git")
    sub = tmp_path / "deep" / "nested" / "dir"
    sub.mkdir(parents=True)
    t = repo_memory.resolve_target(sub)
    assert t.kind == "repo"
    assert t.rel_path == "repos/ricdec/obsidian-knowledge/memory"


def test_resolve_target_repo_no_remote_falls_back_to_host(tmp_path):
    _git_init(tmp_path, remote=None)
    t = repo_memory.resolve_target(tmp_path, hostname="dream-machine")
    assert t.kind == "host"
    assert t.hostname == "dream-machine"
    assert t.rel_path == "systems/machines/dream-machine/memory"


# ── Resolver: host fallback ───────────────────────────────────────────


def test_resolve_target_no_git_uses_host(tmp_path):
    t = repo_memory.resolve_target(tmp_path, hostname="mac-mini")
    assert t.kind == "host"
    assert t.rel_path == "systems/machines/mac-mini/memory"


def test_resolve_target_uses_real_hostname(tmp_path, monkeypatch):
    monkeypatch.setattr(repo_memory.socket, "gethostname", lambda: "Some.Host.local")
    t = repo_memory.resolve_target(tmp_path)
    assert t.kind == "host"
    assert t.hostname == "some"  # stripped + lowercased


def test_safe_hostname_strips_unsafe_chars(monkeypatch):
    monkeypatch.setattr(repo_memory.socket, "gethostname", lambda: "weird/host:name")
    assert repo_memory._safe_hostname() == "weird-host-name"


# ── absolute_target ───────────────────────────────────────────────────


def test_absolute_target_under_vault_wiki(tmp_path):
    target = repo_memory.MemoryTarget(
        kind="repo",
        rel_path="repos/ricdec/obsidian-knowledge/memory",
        owner="ricdec",
        repo="obsidian-knowledge",
        hostname=None,
        remote_url=None,
    )
    abs_path = repo_memory.absolute_target(tmp_path, target)
    assert abs_path == tmp_path / "wiki" / "repos" / "ricdec" / "obsidian-knowledge" / "memory"
