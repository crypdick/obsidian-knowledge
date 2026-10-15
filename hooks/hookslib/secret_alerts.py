"""Stop-hook alert bookkeeping for the vault secret scanner.

Findings alert once; files with unaudited findings get a pointer in needs-attention.md.
"""

from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import os
import tempfile
from collections.abc import Iterator
from pathlib import Path

# Baseline key holding [path, hashed_secret] pairs already surfaced by the Stop hook.
ALERTED_KEY = "vault_alerted"
NEEDS_ATTENTION_PATH = Path("Utility", "obsidian-knowledge", "needs-attention.md")
NEEDS_ATTENTION_HEADING = "## Secret scan findings"


@contextlib.contextmanager
def baseline_lock(vault_root: str) -> Iterator[str]:
    """Serialize scan/merge/save across concurrent sessions on this host.

    Yields the lock path. The lock lives outside the vault so sync tools never see it.
    """
    # NOTE: host-local lock only; sync peers writing the baseline can still race.
    digest = hashlib.sha256(os.path.realpath(vault_root).encode()).hexdigest()[:16]
    lock_path = os.path.join(tempfile.gettempdir(), f".obsidian-knowledge-secrets-{digest}.lock")
    with open(lock_path, "a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield lock_path
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def record_alerts(baseline_path: Path, sample_limit: int) -> tuple[int, list[str], list[str]]:
    """Mark unaudited findings as surfaced; return (new_count, new_sample, unaudited_paths).

    A finding alerts once, keyed by (file, hashed_secret). Audited or removed findings
    drop out of the alerted set, so a later reintroduction alerts again.
    """
    try:
        data = json.loads(baseline_path.read_text())
    except (OSError, json.JSONDecodeError):
        return 0, [], []
    alerted = {tuple(pair) for pair in data.get(ALERTED_KEY, [])}
    current: set[tuple[str, str]] = set()
    sample: list[str] = []
    count = 0
    for filepath, findings in data.get("results", {}).items():
        for f in findings:
            if f.get("is_secret") is not None:
                continue
            key = (filepath, f.get("hashed_secret", ""))
            current.add(key)
            if key in alerted:
                continue
            count += 1
            if len(sample) < sample_limit:
                sample.append(f"{filepath}:{f.get('line_number', '?')} ({f.get('type', 'unknown')})")
    pairs = [list(pair) for pair in sorted(current)]
    if pairs != data.get(ALERTED_KEY, []):
        data[ALERTED_KEY] = pairs
        tmp_path = baseline_path.with_name(baseline_path.name + ".tmp")
        tmp_path.write_text(json.dumps(data, indent=2) + "\n")
        tmp_path.replace(baseline_path)
    return count, sample, sorted({path for path, _ in current})


def sync_needs_attention(vault_root: str, unaudited_paths: list[str]) -> None:
    """Keep one checkbox pointer per file with unaudited findings in needs-attention.md.

    The hook owns only its own section; other sections and existing pointer text are kept.
    """
    page = Path(vault_root) / NEEDS_ATTENTION_PATH
    try:
        lines = page.read_text().splitlines()
    except FileNotFoundError:
        if not unaudited_paths:
            return
        lines = ["# Needs Attention"]
    if NEEDS_ATTENTION_HEADING in lines:
        start = lines.index(NEEDS_ATTENTION_HEADING)
        end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    elif unaudited_paths:
        lines += ["", NEEDS_ATTENTION_HEADING]
        start, end = len(lines) - 1, len(lines)
    else:
        return
    existing = {}
    for line in lines[start + 1 : end]:
        for path in unaudited_paths:
            if line.startswith((f"- [ ] `{path}`", f"- [x] `{path}`")):
                existing[path] = line
    entries = [
        existing.get(
            path,
            f"- [ ] `{path}` — unaudited detect-secrets finding(s). Audit in "
            "`.secrets.baseline` or redact per [[secrets-audit-guide]].",
        )
        for path in unaudited_paths
    ]
    section = [NEEDS_ATTENTION_HEADING, "", *entries, ""] if entries else []
    updated = lines[:start] + section + lines[end:]
    while updated and not updated[-1].strip():
        updated.pop()
    if updated != lines:
        page.parent.mkdir(parents=True, exist_ok=True)
        page.write_text("\n".join(updated) + "\n")
