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


def test_resolve_target_invalid_remote_falls_back_to_host(tmp_path):
    _git_init(tmp_path, "not-a-supported-remote")
    target = repo_memory.resolve_target(tmp_path, hostname="fallback-host")
    assert target.kind == "host"
    assert target.hostname == "fallback-host"


@pytest.mark.parametrize(
    "error",
    [FileNotFoundError(), subprocess.TimeoutExpired(cmd="git", timeout=2)],
)
def test_read_origin_url_returns_none_when_git_is_unavailable(tmp_path, monkeypatch, error):
    def fail(*args, **kwargs):
        raise error

    monkeypatch.setattr(subprocess, "run", fail)
    assert repo_memory.read_origin_url(tmp_path) is None


# ── Resolver: host fallback ───────────────────────────────────────────


def test_resolve_target_no_git_uses_host(tmp_path, monkeypatch):
    # Isolate the no-repository case from .git entries above pytest's temp tree.
    real_exists = Path.exists
    monkeypatch.setattr(Path, "exists", lambda path: False if path.name == ".git" else real_exists(path))
    assert repo_memory.find_git_root(tmp_path) is None
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


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/../../",
        "git@example.com:owner/..",
        "https://example.com/owner/repo%2fescape",
        "https://example.com/owner/repo\\escape",
    ],
)
def test_unsafe_remote_components_rejected(url):
    assert repo_memory.parse_remote_url(url) is None


def test_explicit_hostname_uses_same_sanitization(tmp_path):
    target = repo_memory.resolve_target(tmp_path, hostname="weird/host:name.local")
    assert target.hostname == "weird-host-name"
    assert repo_memory.absolute_target(tmp_path, target).is_relative_to(tmp_path / "wiki")


@pytest.mark.parametrize(
    "kind,owner,repo,hostname,relative",
    [
        ("repo", "..", "project", None, "repos/../project/memory"),
        ("repo", "owner", "project", None, "../../outside"),
        ("host", None, None, "..", "systems/machines/../memory"),
        ("host", "owner", None, "host", "systems/machines/host/memory"),
    ],
)
def test_memory_target_rejects_inconsistent_identity(kind, owner, repo, hostname, relative):
    with pytest.raises(ValueError):
        repo_memory.MemoryTarget(kind, relative, owner, repo, hostname, None)


def test_memory_target_rejects_symlink_escape(tmp_path):
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (wiki / "repos").symlink_to(outside, target_is_directory=True)
    target = repo_memory.MemoryTarget("repo", "repos/owner/project/memory", "owner", "project", None, None)
    with pytest.raises(ValueError, match="outside wiki"):
        repo_memory.absolute_target(tmp_path, target)
