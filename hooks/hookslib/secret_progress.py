"""Host-local secret-scan completion, independent of editable finding metadata."""

from __future__ import annotations

import hashlib
import logging
import os
from collections.abc import Callable
from pathlib import Path

from pydantic import BaseModel, Field


class ScanProgress(BaseModel):
    revision: int = 0
    baseline: str = ""
    files: dict[str, str] = Field(default_factory=dict)

    @classmethod
    def load(cls, path: Path) -> ScanProgress:
        try:
            return cls.model_validate_json(path.read_text())
        except (OSError, ValueError):
            return cls()

    def save(self, path: Path) -> None:
        temporary = path.with_suffix(".tmp")
        try:
            temporary.write_text(self.model_dump_json())
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)


def content_version(path: Path) -> tuple[str, int, int, int] | None:
    """Hash content; metadata changes during read prevent claiming completion."""
    try:
        with path.open("rb") as source:
            before = os.fstat(source.fileno())
            digest = hashlib.file_digest(source, "sha256").hexdigest()
            after = os.fstat(source.fileno())
        if (before.st_mtime_ns, before.st_ctime_ns, before.st_size) != (
            after.st_mtime_ns,
            after.st_ctime_ns,
            after.st_size,
        ):
            return None
        return digest, after.st_mtime_ns, after.st_ctime_ns, after.st_size
    except OSError:
        return None


def content_digest(path: Path) -> str:
    version = content_version(path)
    return version[0] if version else ""


class ScanDiagnostics(logging.Handler):
    """detect-secrets reports swallowed file errors through its public logger."""

    def __init__(self) -> None:
        super().__init__(level=logging.WARNING)
        self.failed = False

    def emit(self, record: logging.LogRecord) -> None:
        self.failed = True


def scan_completed(scan_file: Callable[[str], None], path: str) -> bool:
    """Any backend warning/error prevents claiming this file version complete."""
    diagnostics = ScanDiagnostics()
    backend = logging.getLogger("detect-secrets")
    previous_level = backend.level
    # The library defaults to ERROR, suppressing its own swallowed-read warnings.
    backend.setLevel(logging.WARNING)
    backend.addHandler(diagnostics)
    try:
        scan_file(path)
    finally:
        backend.removeHandler(diagnostics)
        backend.setLevel(previous_level)
    return not diagnostics.failed
