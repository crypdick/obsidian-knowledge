"""Durable, low-friction recording of agent workflow papercuts."""

from __future__ import annotations

import contextlib
import fcntl
import os
import re
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

PAPERCUTS_FILENAME = "PAPERCUTS.md"
GLOBAL_PAPERCUTS_RELATIVE_PATH = Path("wiki/systems/knowledge-base") / PAPERCUTS_FILENAME
REPO_PAPERCUTS_ROOT = Path("wiki/repos")

_NETWORK_REMOTE_SCHEMES = {"git", "git+ssh", "http", "https", "ssh"}
_SCP_STYLE_REMOTE_RE = re.compile(r"^(?:[^@/\s:]+@)?[^/\s:]+:(?P<path>[^/\s:].*)$")
_SAFE_REPOSITORY_COMPONENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


@dataclass(frozen=True)
class _PapercutScope:
    """Vault-relative destination and metadata for one papercut log."""

    relative_path: Path
    kind: str
    repository: str | None = None


@dataclass(frozen=True)
class PapercutRecord:
    """The append-only papercut log updated by one command invocation."""

    path: Path


def record_papercut(
    vault_root: Path,
    description: str,
    *,
    cwd: Path | None = None,
    now: datetime | None = None,
) -> PapercutRecord:
    """Append one papercut to the repository-specific log under ``vault_root``.

    This deliberately does not diagnose, deduplicate, or implement a fix.
    Repeated reports are useful evidence that a friction point recurs.
    """
    report = description.strip()
    if not report:
        raise ValueError("papercut description must not be blank")

    vault = vault_root.expanduser().resolve()
    if not vault.is_dir():
        raise ValueError(f"vault does not exist or is not a directory: {vault}")

    timestamp = (now or datetime.now(UTC)).astimezone(UTC)
    working_directory = (cwd or Path.cwd()).expanduser().resolve()
    scope = _scope_for(working_directory)
    log_path = vault / scope.relative_path
    log_path.parent.mkdir(parents=True, exist_ok=True)

    with _log_lock(log_path):
        _ensure_log_header(log_path, scope)
        _append_papercut(log_path, report, timestamp, working_directory)

    return PapercutRecord(path=log_path)


def _scope_for(working_directory: Path) -> _PapercutScope:
    """Prefer a stable per-repository log, with a central fallback."""
    repository = _repository_from_origin(working_directory)
    if repository is None:
        return _PapercutScope(relative_path=GLOBAL_PAPERCUTS_RELATIVE_PATH, kind="global")

    owner, repo = repository
    return _PapercutScope(
        relative_path=REPO_PAPERCUTS_ROOT / owner / repo / PAPERCUTS_FILENAME,
        kind="repo",
        repository=f"{owner}/{repo}",
    )


def _repository_from_origin(working_directory: Path) -> tuple[str, str] | None:
    """Return a path-safe owner/repo identity for the enclosing Git repo."""
    git_directory = working_directory if working_directory.is_dir() else working_directory.parent
    try:
        result = subprocess.run(
            ["git", "-C", str(git_directory), "remote", "get-url", "origin"],
            capture_output=True,
            check=False,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return _parse_repository_identity(result.stdout)


def _parse_repository_identity(remote_url: str) -> tuple[str, str] | None:
    """Extract a safe final owner/repo pair from a standard Git remote URL."""
    path = _repository_path_from_remote(remote_url)
    if path is None:
        return None
    components = path.strip("/").split("/")
    if len(components) < 2 or any(not component for component in components):
        return None
    owner, repo = components[-2], components[-1].removesuffix(".git")
    if not (_is_safe_repository_component(owner) and _is_safe_repository_component(repo)):
        return None
    return owner, repo


def _repository_path_from_remote(remote_url: str) -> str | None:
    """Return the repository path from a canonical hosted or scp-style remote."""
    url = remote_url.strip()
    parsed = urlparse(url)
    if parsed.scheme in _NETWORK_REMOTE_SCHEMES and parsed.netloc:
        return parsed.path

    match = _SCP_STYLE_REMOTE_RE.fullmatch(url)
    if match is None:
        return None
    return match.group("path")


def _is_safe_repository_component(component: str) -> bool:
    return component not in {".", ".."} and bool(_SAFE_REPOSITORY_COMPONENT_RE.fullmatch(component))


@contextlib.contextmanager
def _log_lock(log_path: Path):
    """Serialize appends so concurrent agents cannot interleave entries."""
    lock_path = log_path.with_name(f".{log_path.name}.lock")
    with lock_path.open("a", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _ensure_log_header(log_path: Path, scope: _PapercutScope) -> None:
    """Create the log once without ever rewriting a pre-existing user file."""
    try:
        with log_path.open("x", encoding="utf-8") as log_file:
            log_file.write(_format_log_header(scope))
            log_file.flush()
            os.fsync(log_file.fileno())
    except FileExistsError:
        pass


def _append_papercut(
    log_path: Path,
    report: str,
    timestamp: datetime,
    working_directory: Path,
) -> None:
    """Durably append one independently readable record to a papercut log."""
    with log_path.open("a", encoding="utf-8") as log_file:
        log_file.write(_format_entry(report, timestamp, working_directory))
        log_file.flush()
        os.fsync(log_file.fileno())


def _format_log_header(scope: _PapercutScope) -> str:
    repository_line = f"repository: {scope.repository}\n" if scope.repository else ""
    title = f"# Papercuts — {scope.repository}" if scope.repository else "# Papercuts"
    return (
        "---\n"
        "type: papercut-log\n"
        f"scope: {scope.kind}\n"
        f"{repository_line}"
        "---\n\n"
        f"{title}\n\n"
        "> Append-only agent-observed workflow friction. Investigate or fix entries separately.\n"
    )


def _format_entry(report: str, timestamp: datetime, working_directory: Path) -> str:
    created = timestamp.strftime("%Y-%m-%d %H:%M:%S UTC")
    safe_cwd = str(working_directory).replace("`", "\\`")
    return f"\n## {created}\n\n- Status: open\n- Working directory: `{safe_cwd}`\n\n{report}\n"
