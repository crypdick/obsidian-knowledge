"""Host-local secret-scan completion, independent of editable finding metadata."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import signal
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class ScanProgress(BaseModel):
    revision: int = 0
    files: dict[str, tuple[str, str]] = Field(default_factory=dict)

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


class BaselineResults(BaseModel):
    results: dict[str, list[dict[str, Any]]]


def finding_versions(path: Path) -> dict[str, str] | None:
    """Fingerprint each file's findings; alert metadata must not invalidate scan progress."""
    try:
        baseline = BaselineResults.model_validate_json(path.read_text())
    except (OSError, ValueError):
        return None
    return fingerprint_findings(baseline.results)


def fingerprint_findings(results: dict[str, list[dict[str, Any]]]) -> dict[str, str]:
    return {
        name: hashlib.sha256(
            json.dumps(sorted(json.dumps(item, sort_keys=True) for item in findings)).encode()
        ).hexdigest()
        for name, findings in results.items()
        if findings
    }


class ScanDiagnostics(logging.Handler):
    """detect-secrets reports swallowed file errors through its public logger."""

    def __init__(self) -> None:
        super().__init__(level=logging.WARNING)
        self.failed = False

    def emit(self, record: logging.LogRecord) -> None:
        self.failed = True


# NOTE: docs/hooks.md describes files that stay pending after detector timeout.
DETECTOR_TIMEOUT_SECONDS = 10


class DetectorTimeout(Exception):
    """A detector did not finish scanning this file."""


def detector_timeout(signum: int, frame: object) -> None:
    raise DetectorTimeout


def scan_completed(scan_file: Callable[[str], None], path: str) -> bool:
    """Any backend warning/error prevents claiming this file version complete."""
    diagnostics = ScanDiagnostics()
    backend = logging.getLogger("detect-secrets")
    previous_level = backend.level
    # The library defaults to ERROR, suppressing its own swallowed-read warnings.
    backend.setLevel(logging.WARNING)
    backend.addHandler(diagnostics)
    previous_handler = signal.signal(signal.SIGALRM, detector_timeout)
    signal.setitimer(signal.ITIMER_REAL, DETECTOR_TIMEOUT_SECONDS)
    try:
        scan_file(path)
    except DetectorTimeout:
        return False
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)
        backend.removeHandler(diagnostics)
        backend.setLevel(previous_level)
    return not diagnostics.failed
