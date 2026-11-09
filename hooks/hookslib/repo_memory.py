"""Resolve where per-repo agent memory should live in the Obsidian vault.

The agent's "auto-memory" facts (feedback/project/reference rules) used to
land in `~/.claude/projects/<slugified-abs-path>/memory/`. That is:
  - invisible to other sessions started outside that exact path
  - invisible to other tools and to obsidian-knowledge search
  - not portable across hosts (the slug embeds the absolute cwd)

This module computes a stable, host-agnostic vault-relative path keyed on
the GitHub `<owner>/<repo>` parsed from the cwd's git remote. Falls back
to `systems/machines/<hostname>/memory/` for sessions outside any repo
(so the user's existing per-host folders pick up host-scoped facts).

Returned `rel_path` is always relative to `<vault>/wiki/`.
"""

from __future__ import annotations

import re
import socket
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class MemoryTarget:
    """Where to write a memory file. rel_path is under <vault>/wiki/."""

    kind: str  # "repo" | "host"
    rel_path: str  # e.g. "repos/anthropics/claude-code/memory"
    owner: str | None  # github user/org (kind=repo)
    repo: str | None  # repo name (kind=repo)
    hostname: str | None  # (kind=host)
    remote_url: str | None  # diagnostic; None for kind=host

    def __post_init__(self) -> None:
        if self.kind == "repo" and self.owner and self.repo and self.hostname is None:
            if not all(_safe_component(value) for value in (self.owner, self.repo)):
                raise ValueError("unsafe repository memory identity")
            expected = f"repos/{self.owner}/{self.repo}/memory"
        elif self.kind == "host" and self.hostname and self.owner is None and self.repo is None:
            if not _safe_component(self.hostname):
                raise ValueError("unsafe hostname memory identity")
            expected = f"systems/machines/{self.hostname}/memory"
        else:
            raise ValueError("inconsistent memory identity")
        if self.rel_path != expected:
            raise ValueError("memory path does not match identity")


# Match owner/repo from common git remote URL shapes.
# Examples:
#   git@github.com:Anthropic/claude-code.git
#   https://github.com/Anthropic/claude-code.git
#   ssh://git@github.com/Anthropic/claude-code
#   git@gitlab.com:group/sub/project.git  (we take the *last two* segments)
_REMOTE_TAIL_RE = re.compile(
    r"""
    (?:[:/])                  # ':' (scp-style) or '/' (URL)
    (?P<owner>[^/:\s]+)       # owner / org / group
    /
    (?P<repo>[^/:\s]+?)       # repo name
    (?:\.git)?                # optional .git suffix
    /?$                       # optional trailing slash
    """,
    re.VERBOSE,
)


def parse_remote_url(url: str) -> tuple[str, str] | None:
    """Return (owner, repo) parsed from a git remote URL, or None.

    Takes the last `<owner>/<repo>` pair so it works for nested groups
    too (e.g. GitLab subgroups), but does not preserve them — collisions
    across hosts/subgroups are accepted as out-of-scope for now.
    """
    # NOTE: docs/hooks.md documents portable identity and wiki confinement.
    if not url:
        return None
    m = _REMOTE_TAIL_RE.search(url.strip())
    if not m:
        return None
    owner, repo = m.group("owner"), m.group("repo")
    if not all(_safe_component(part) for part in (owner, repo)):
        return None
    return owner, repo


def find_git_root(start: Path) -> Path | None:
    """Walk up from `start` looking for a .git dir/file. Return repo root."""
    start = start.resolve()
    for d in (start, *start.parents):
        if (d / ".git").exists():
            return d
    return None


def read_origin_url(repo_root: Path) -> str | None:
    """Return the `origin` remote URL for repo_root, or None."""
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo_root), "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    out = proc.stdout.strip()
    return out or None


def _safe_component(value: str) -> bool:
    return value not in {".", ".."} and re.fullmatch(r"[A-Za-z0-9._-]+", value) is not None


def _safe_hostname(hostname: str | None = None) -> str:
    """Hostname stripped of the .local suffix; lowercased; safe for path."""
    h = (socket.gethostname() if hostname is None else hostname).split(".")[0].lower()
    # Keep it Syncthing-clean across Linux/macOS/Android.
    return re.sub(r"[^a-z0-9._-]", "-", h) or "unknown-host"


def resolve_target(cwd: str | Path, *, hostname: str | None = None) -> MemoryTarget:
    """Compute the memory target for `cwd`.

    Repo case (preferred): git remote origin → `repos/<owner>/<repo>/memory`.
    Otherwise: `systems/machines/<hostname>/memory`.
    """
    cwd = Path(cwd)
    repo_root = find_git_root(cwd)
    if repo_root is not None:
        url = read_origin_url(repo_root)
        if url is not None:
            parsed = parse_remote_url(url)
            if parsed is not None:
                owner, repo = parsed
                return MemoryTarget(
                    kind="repo",
                    rel_path=f"repos/{owner}/{repo}/memory",
                    owner=owner,
                    repo=repo,
                    hostname=None,
                    remote_url=url,
                )
    host = _safe_hostname(hostname)
    return MemoryTarget(
        kind="host",
        rel_path=f"systems/machines/{host}/memory",
        owner=None,
        repo=None,
        hostname=host,
        remote_url=None,
    )


def absolute_target(vault_root: str | Path, target: MemoryTarget) -> Path:
    """Return the absolute filesystem path under <vault>/wiki/."""
    wiki = (Path(vault_root) / "wiki").resolve()
    path = (wiki / target.rel_path).resolve()
    if not path.is_relative_to(wiki):
        raise ValueError("memory target resolves outside wiki")
    return path
