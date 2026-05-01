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

Known-leaked literal blacklist
------------------------------

detect-secrets misses low-entropy passwords mentioned in narrative
text (no `password=value` keyword pattern, dictionary words below the
entropy threshold). To catch those, this hook also greps for literal
strings listed one-per-line in `<vault>/.secrets.known-leaked`:

    # Comments and blank lines ignored.
    legacy-password-1
    some-other-leaked-string

Each match becomes a separate finding in the surfaced reminder. The
file itself is excluded from scanning. Add a string here once you've
discovered a real password leaked into vault narrative — future
re-introductions of the same string will be flagged immediately.
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
    r"\.secrets\.baseline$|\.secrets\.known-leaked$|"
    r"\.(png|jpg|jpeg|gif|webp|svg|pdf|mp4|mp3|zip|tar|gz|woff2?)$)"
)

SKIP_DIRS = {".git", ".obsidian", "_sources", "node_modules", ".venv"}

KNOWN_LEAKED_FILENAME = ".secrets.known-leaked"
# Cap reported known-leaked matches per scan to keep the reminder
# readable. Once one literal hits dozens of files, the agent has
# enough signal — listing each occurrence drowns the reminder.
KNOWN_LEAKED_SAMPLE_LIMIT = 10

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

KNOWN_LEAKED_REMINDER_TEMPLATE = (
    "Known-leaked literal(s) from .secrets.known-leaked still present in vault "
    "({count} occurrence(s) across {file_count} file(s); showing up to "
    f"{KNOWN_LEAKED_SAMPLE_LIMIT}):\n"
    "{sample}\n"
    "Each match is a verbatim copy of a string you previously flagged as "
    "leaked. Redact the occurrence (replace with a reference to the password "
    "manager) or remove the literal from .secrets.known-leaked if it's no "
    "longer sensitive."
)


def load_known_leaked(vault_root: str) -> list[str]:
    """Read literal blacklist from <vault>/.secrets.known-leaked.

    One literal per line. Lines that are blank or start with `#` are
    ignored (comments). Returns [] if the file is absent or unreadable.
    """
    path = Path(vault_root) / KNOWN_LEAKED_FILENAME
    try:
        text = path.read_text()
    except (OSError, UnicodeDecodeError):
        return []
    out: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        out.append(stripped)
    return out


def scan_known_leaked(
    paths: list[str], literals: list[str]
) -> tuple[int, int, list[str]]:
    """Grep `paths` for literal occurrences of any string in `literals`.

    Returns `(total_matches, files_with_matches, sample)` where
    `sample` is a list of `path:line_number :: literal` strings,
    capped at KNOWN_LEAKED_SAMPLE_LIMIT.
    """
    if not paths or not literals:
        return 0, 0, []
    total = 0
    files_hit: set[str] = set()
    sample: list[str] = []
    for path in paths:
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                for lineno, line in enumerate(f, start=1):
                    for literal in literals:
                        if literal in line:
                            total += 1
                            files_hit.add(path)
                            if len(sample) < KNOWN_LEAKED_SAMPLE_LIMIT:
                                sample.append(f"{path}:{lineno} :: {literal}")
        except OSError:
            continue
    return total, len(files_hit), sample


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

    # Known-leaked literals: walk every file in the vault, not just
    # mtime-changed ones, so a literal added to .secrets.known-leaked
    # surfaces existing occurrences immediately.
    literals = load_known_leaked(vault_root)
    if literals:
        all_paths = find_files(vault_root)
        all_paths = [
            p for p in all_paths
            if not p.endswith((KNOWN_LEAKED_FILENAME, ".secrets.baseline"))
        ]
        leaked_count, leaked_files, leaked_sample = scan_known_leaked(
            all_paths, literals
        )
    else:
        leaked_count, leaked_files, leaked_sample = 0, 0, []

    messages: list[str] = []
    if count > 0:
        sample_block = "\n".join(f"  {s}" for s in sample)
        messages.append(
            REMINDER_TEMPLATE.format(count=count, sample=sample_block)
        )
    if leaked_count > 0:
        leaked_block = "\n".join(f"  {s}" for s in leaked_sample)
        messages.append(
            KNOWN_LEAKED_REMINDER_TEMPLATE.format(
                count=leaked_count,
                file_count=leaked_files,
                sample=leaked_block,
            )
        )

    if not messages:
        sys.exit(0)
    emit_block("\n\n".join(messages))


if __name__ == "__main__":
    main()
