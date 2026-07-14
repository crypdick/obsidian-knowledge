"""Durable, low-friction recording of agent workflow papercuts."""

from __future__ import annotations

import contextlib
import fcntl
import os
import re
import tempfile
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

PAPERCUTS_RELATIVE_DIR = Path("wiki/systems/knowledge-base/papercuts")
PAPERCUTS_INDEX_NAME = "index.md"


@dataclass(frozen=True)
class PapercutRecord:
    """Result of recording a papercut.

    ``index_error`` is intentionally non-fatal: the immutable report is the
    primary outcome, while its directory index can be rebuilt on a later run.
    """

    path: Path
    index_error: str | None = None


def record_papercut(
    vault_root: Path,
    description: str,
    *,
    cwd: Path | None = None,
    now: datetime | None = None,
) -> PapercutRecord:
    """Create one immutable papercut report under ``vault_root``.

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
    papercuts_dir = vault / PAPERCUTS_RELATIVE_DIR
    papercuts_dir.mkdir(parents=True, exist_ok=True)

    report_path = papercuts_dir / _filename_for(report, timestamp)
    while True:
        try:
            with report_path.open("x", encoding="utf-8") as report_file:
                report_file.write(_format_report(report, timestamp, working_directory))
            break
        except FileExistsError:
            report_path = papercuts_dir / _filename_for(report, timestamp)

    try:
        with _index_lock(papercuts_dir):
            _rebuild_papercuts_index(papercuts_dir)
    except OSError as exc:
        return PapercutRecord(path=report_path, index_error=str(exc))
    return PapercutRecord(path=report_path)


def _filename_for(report: str, timestamp: datetime) -> str:
    return f"{timestamp:%Y-%m-%d-%H%M%S}-{_slugify(report)}-{uuid.uuid4().hex[:8]}.md"


def _slugify(text: str) -> str:
    words = re.findall(r"[a-z0-9]+", text.casefold())
    slug = "-".join(words)[:72].strip("-")
    return slug or "papercut"


def _format_report(report: str, timestamp: datetime, working_directory: Path) -> str:
    created = timestamp.isoformat(timespec="seconds").replace("+00:00", "Z")
    safe_cwd = str(working_directory).replace("`", "\\`")
    return (
        "---\n"
        f"created: {created}\n"
        "type: papercut\n"
        "status: open\n"
        "---\n\n"
        "# Papercut\n\n"
        "## Friction\n\n"
        f"{report}\n\n"
        "## Context\n\n"
        f"- Working directory: `{safe_cwd}`\n"
    )


@contextlib.contextmanager
def _index_lock(papercuts_dir: Path):
    """Serialize local index rewrites while keeping reports independently safe."""
    lock_path = papercuts_dir / ".papercuts.lock"
    with lock_path.open("a", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _rebuild_papercuts_index(papercuts_dir: Path) -> None:
    reports = sorted(
        (path for path in papercuts_dir.glob("*.md") if path.name != PAPERCUTS_INDEX_NAME),
        key=lambda path: path.name,
        reverse=True,
    )
    entries = [f"- [[{path.stem}]] — agent-observed workflow friction" for path in reports]
    body = "# Papercuts\n"
    if entries:
        body += "\n" + "\n".join(entries) + "\n"
    _atomic_write(papercuts_dir / PAPERCUTS_INDEX_NAME, body)


def _atomic_write(path: Path, text: str) -> None:
    """Replace ``path`` atomically, preserving a complete index on interruption."""
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent, text=True)
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as temporary:
            temporary.write(text)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temp_path, path)
    finally:
        temp_path.unlink(missing_ok=True)
