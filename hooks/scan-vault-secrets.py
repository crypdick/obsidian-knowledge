#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["detect-secrets"]
# ///
"""Stop hook: scan the vault for leaked secrets and surface findings.

Vault detection: cwd must be inside a configured vault root from
~/.config/obsidian-knowledge/vaults.yaml. Cooldown: at most one scan
per session per 5 minutes, tracked via a /tmp marker's mtime.

First run (or missing baseline) does a full scan of the vault.
Subsequent runs are incremental: only files modified since the last
scan are passed to detect-secrets, which merges findings into the
baseline at <vault>/.secrets.baseline.

Unaudited findings trigger a reminder pointing the agent at the
vault's documented secrets-management convention (the plugin makes no
assumptions about which password manager you use). False positives
are dismissed by running, in the vault root:

    detect-secrets audit .secrets.baseline
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib.stop_hook import emit_block, in_cooldown, read_input  # noqa: E402
from lib.vault_config import is_in_vault, load_vault_roots  # noqa: E402
from lib.vault_policy import find_containing_vault  # noqa: E402

EXCLUDE_REGEX = (
    r"(\.syncthing\.|sync-conflict-|\.tmp$|"
    r"/\.git/|/\.obsidian/|/_sources/|/node_modules/|/\.venv/|"
    r"\.secrets\.baseline$|"
    r"\.(png|jpg|jpeg|gif|webp|svg|pdf|mp4|mp3|zip|tar|gz|woff2?)$)"
)

SKIP_DIRS = {".git", ".obsidian", "_sources", "node_modules", ".venv"}

SCAN_TIMEOUT_SECONDS = 120
# Cap files per detect-secrets invocation to stay clear of ARG_MAX on
# large vaults. Each call merges into the baseline, so chunking is
# transparent. Empirically ~0.2s per 500-file chunk.
SCAN_BATCH_SIZE = 500


def find_files(root: str, since_mtime: float = 0.0) -> list[str]:
    """Return regular files under `root` with mtime > `since_mtime`.

    `since_mtime=0.0` returns every file (full bootstrap walk).
    """
    out: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            p = os.path.join(dirpath, fn)
            try:
                if os.path.getmtime(p) > since_mtime:
                    out.append(p)
            except OSError:
                continue
    return out


def run_scan(baseline: Path, paths: list[str]) -> None:
    """Scan `paths` with detect-secrets, merging findings into `baseline`.

    Bootstrap (no baseline yet): the first batch creates the baseline
    from stdout. Subsequent batches merge via --baseline. Silent on
    detect-secrets errors so the hook does not break the session.

    detect-secrets requires git for directory walks, so callers must
    pass explicit file paths.
    """
    if not paths:
        return
    for i in range(0, len(paths), SCAN_BATCH_SIZE):
        batch = paths[i : i + SCAN_BATCH_SIZE]
        if baseline.exists():
            cmd = [
                "detect-secrets",
                "scan",
                "--baseline",
                str(baseline),
                "--exclude-files",
                EXCLUDE_REGEX,
                *batch,
            ]
            try:
                subprocess.run(
                    cmd, capture_output=True, timeout=SCAN_TIMEOUT_SECONDS, check=False
                )
            except (subprocess.SubprocessError, FileNotFoundError):
                return
        else:
            cmd = [
                "detect-secrets",
                "scan",
                "--exclude-files",
                EXCLUDE_REGEX,
                *batch,
            ]
            try:
                result = subprocess.run(
                    cmd, capture_output=True, timeout=SCAN_TIMEOUT_SECONDS, check=False
                )
            except (subprocess.SubprocessError, FileNotFoundError):
                return
            if result.returncode == 0 and result.stdout:
                baseline.write_bytes(result.stdout)


def count_unaudited(baseline: Path) -> tuple[int, list[str]]:
    """Return (count, sample) for unaudited (is_secret=null) findings."""
    try:
        data = json.loads(baseline.read_text())
    except (OSError, json.JSONDecodeError):
        return 0, []
    results = data.get("results", {})
    sample: list[str] = []
    count = 0
    for filepath, findings in results.items():
        for f in findings:
            if f.get("is_secret") is None:
                count += 1
                if len(sample) < 10:
                    sample.append(
                        f"{filepath}:{f.get('line_number', '?')} "
                        f"({f.get('type', 'unknown')})"
                    )
    return count, sample


REMINDER_TEMPLATE = (
    "detect-secrets found {count} unaudited finding(s) in the vault:\n"
    "{sample}\n"
    "Remediate each per the vault's documented secrets-management convention "
    "(search the vault for it; if missing, ask the user). For real secrets: "
    "store via the vault's password-manager workflow, replace inline with a "
    "reference, then re-scan. For false positives run, in the vault root:\n"
    "    detect-secrets audit .secrets.baseline"
)


def main() -> None:
    if not is_in_vault(os.getcwd()):
        sys.exit(0)
    payload = read_input()

    if in_cooldown(payload, marker_basename="secrets-scan"):
        sys.exit(0)

    vault_root = find_containing_vault(os.getcwd(), load_vault_roots())
    if not vault_root:
        sys.exit(0)

    baseline = Path(vault_root) / ".secrets.baseline"
    # Baseline mtime is the vault-global "last scanned" signal — using
    # the per-session cooldown marker here would force a full scan in
    # every new session.
    if not baseline.exists():
        scan_paths = find_files(vault_root)
    else:
        scan_paths = find_files(vault_root, since_mtime=baseline.stat().st_mtime)
        if not scan_paths:
            sys.exit(0)

    run_scan(baseline, scan_paths)
    count, sample = count_unaudited(baseline)
    if count == 0:
        sys.exit(0)

    sample_block = "\n".join(f"  {s}" for s in sample)
    emit_block(REMINDER_TEMPLATE.format(count=count, sample=sample_block))


if __name__ == "__main__":
    main()
