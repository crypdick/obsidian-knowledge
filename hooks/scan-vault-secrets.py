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
Subsequent runs are incremental: only files modified since the baseline
mtime are rescanned. Findings merge into the baseline at
<vault>/.secrets.baseline, preserving audit decisions on findings that
still exist after the rescan.

Implementation
--------------

Uses the detect-secrets Python API (`SecretsCollection`) directly,
not the `detect-secrets scan` CLI. The CLI applies a heavier filter
chain tuned for code repositories — `is_likely_id_string` and
`is_indirect_reference` in particular drop high-entropy values that
look like `token = "..."`, which is exactly the pattern leaked
secrets take in prose notes. The Python API path lets us pick a
filter set tuned for vault content.

Filter set
----------

Kept (filter out non-content noise):
- is_line_allowlisted     — sentinel support (see below)
- is_invalid_file         — unreadable / nonexistent
- is_non_text_file        — binary content
- is_lock_file            — package-lock.json, etc.
- is_swagger_file         — OpenAPI spec example values
- is_not_alphanumeric_string
- is_sequential_string    — "abcdef..." padding

Dropped (would suppress prose-note leaks):
- is_likely_id_string     — drops 'token = "..."' as "looks like an ID"
- is_indirect_reference   — drops anything resembling a variable ref
- is_potential_uuid
- is_templated_secret
- is_prefixed_with_dollar_sign

Allowlist sentinel
------------------

To mark a finding as not-a-secret without auditing the baseline,
append a comment to the line:

    token = "fake-example"  <!-- pragma: allowlist secret -->     (markdown / xml)
    token = "fake-example"  # pragma: allowlist secret            (yaml / sh / py)
    token = "fake-example"  // pragma: allowlist secret           (js / go / java)
    -- pragma: allowlist secret                                   (sql)

`is_line_allowlisted` recognises the sentinel for the comment style
matching the file extension, plus all comment styles for unknown
extensions.

Marking false positives in the baseline (alternative)
-----------------------------------------------------

For findings already in the baseline, run in the vault root:

    detect-secrets audit .secrets.baseline

This walks each finding and lets you mark it real / false-positive
once, persisting the decision so future scans don't re-surface it.

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

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib.stop_hook import emit_block, in_cooldown, read_input  # noqa: E402
from lib.vault_config import is_in_vault, load_vault_roots  # noqa: E402
from lib.vault_policy import find_containing_vault  # noqa: E402

# detect_secrets is imported lazily inside run_scan() so this module
# can be imported in environments that don't have it installed (e.g.
# unit tests that exercise only load_known_leaked / scan_known_leaked).
# At runtime the script is launched via `uv run --script`, which
# resolves the inline PEP 723 dep block at the top of the file.

# Hidden dirs (anything starting with '.') are tooling/state, not user
# content — skipping them avoids torrents of false positives in
# `.improve-harness/`, `.foam/`, etc. _sources/ holds read-only
# originals (tax, legal); not scannable by hook policy anyway.
SKIP_NAMED_DIRS = {"_sources", "node_modules"}

EXCLUDE_EXTS = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg",
    ".pdf", ".mp4", ".mp3", ".zip", ".tar", ".gz",
    ".woff", ".woff2",
}

KNOWN_LEAKED_FILENAME = ".secrets.known-leaked"
BASELINE_FILENAME = ".secrets.baseline"
# Cap reported known-leaked matches per scan to keep the reminder
# readable. Once one literal hits dozens of files, the agent has
# enough signal — listing each occurrence drowns the reminder.
KNOWN_LEAKED_SAMPLE_LIMIT = 10
UNAUDITED_SAMPLE_LIMIT = 10

PLUGINS = [
    "AWSKeyDetector", "ArtifactoryDetector", "AzureStorageKeyDetector",
    "Base64HighEntropyString", "BasicAuthDetector", "CloudantDetector",
    "DiscordBotTokenDetector", "GitHubTokenDetector", "GitLabTokenDetector",
    "HexHighEntropyString", "IbmCloudIamDetector", "IbmCosHmacDetector",
    "JwtTokenDetector", "KeywordDetector", "MailchimpDetector",
    "NpmDetector", "OpenAIDetector", "PrivateKeyDetector",
    "PypiTokenDetector", "SendGridDetector", "SlackDetector",
    "SoftlayerDetector", "SquareOAuthDetector", "StripeDetector",
    "TelegramBotTokenDetector", "TwilioKeyDetector",
]

DETECT_SECRETS_CFG = {
    "plugins_used": [{"name": p} for p in PLUGINS],
    "filters_used": [
        {"path": "detect_secrets.filters.allowlist.is_line_allowlisted"},
        {"path": "detect_secrets.filters.common.is_invalid_file"},
        {"path": "detect_secrets.filters.heuristic.is_non_text_file"},
        {"path": "detect_secrets.filters.heuristic.is_lock_file"},
        {"path": "detect_secrets.filters.heuristic.is_swagger_file"},
        {"path": "detect_secrets.filters.heuristic.is_not_alphanumeric_string"},
        {"path": "detect_secrets.filters.heuristic.is_sequential_string"},
    ],
}


def find_files(root: str, since_mtime: float = 0.0) -> list[str]:
    """Return regular files under `root` with mtime > `since_mtime`.

    Returns paths RELATIVE to `root` so that they match the keys
    detect-secrets stores in the baseline. `since_mtime=0.0` returns
    every file (full bootstrap walk). Skips hidden directories and
    known noise directories.
    """
    out: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            d for d in dirnames
            if not d.startswith(".") and d not in SKIP_NAMED_DIRS
        ]
        for fn in filenames:
            ext = os.path.splitext(fn)[1].lower()
            if ext in EXCLUDE_EXTS:
                continue
            if fn in {BASELINE_FILENAME, KNOWN_LEAKED_FILENAME}:
                continue
            absolute = os.path.join(dirpath, fn)
            try:
                if os.path.getmtime(absolute) > since_mtime:
                    out.append(os.path.relpath(absolute, root))
            except OSError:
                continue
    return out


def run_scan(
    baseline_path: Path,
    vault_root: str,
    scan_paths: list[str],
    all_paths: list[str],
) -> None:
    """Scan `scan_paths` and merge into baseline at `baseline_path`.

    All path arguments are vault-relative. `scan_paths` are files
    we'll rescan (changed since last scan). `all_paths` is every
    currently-existing scannable file — used to drop baseline entries
    for files that have been deleted or renamed since the prior scan.

    Audit decisions on unchanged findings are preserved. Unchanged
    files keep their old `PotentialSecret` objects (with audit flags
    intact). Rescanned files get fresh `PotentialSecret` objects (no
    audit flags); `merge()` then copies audit flags forward from the
    old baseline where the secret hash still matches.
    """
    from detect_secrets.core import baseline as ds_baseline
    from detect_secrets.core.secrets_collection import SecretsCollection
    from detect_secrets.settings import transient_settings

    with transient_settings(DETECT_SECRETS_CFG):
        # `root=vault_root` makes scans behave as-if cwd were the vault
        # root: stored filenames are vault-relative, audit flags survive
        # baseline reload regardless of where the hook was invoked from.
        fresh_sc = SecretsCollection(root=vault_root)
        if scan_paths:
            fresh_sc.scan_files(*scan_paths)

        old_sc: SecretsCollection | None = None
        if baseline_path.exists():
            try:
                old_data = ds_baseline.load_from_file(str(baseline_path))
                old_sc = SecretsCollection.load_from_baseline(old_data)
            except Exception:
                old_sc = None

        result_sc = SecretsCollection(root=vault_root)
        if old_sc is not None:
            # Carry forward old findings for files we did NOT rescan
            # and that still exist. The PotentialSecret objects retain
            # their audit flags as-is.
            still_present = set(all_paths)
            rescanned = set(scan_paths)
            for fp in list(old_sc.files):
                if fp not in rescanned and fp in still_present:
                    result_sc.data[fp] = old_sc.data[fp]

        # Add fresh scan findings (audit flags blank — populated by
        # merge() below where old finding hash still matches).
        for fp in fresh_sc.files:
            result_sc.data[fp] = fresh_sc.data[fp]

        if old_sc is not None:
            result_sc.merge(old_sc)

        _save_if_changed(result_sc, baseline_path, ds_baseline)


def _save_if_changed(result_sc, baseline_path: Path, ds_baseline) -> None:
    """Write baseline only if findings differ from existing on disk.

    detect_secrets stamps `generated_at` on every save_to_file call. With
    multiple concurrent Claude Code sessions on the same host (and across
    sync peers), unconditional saves produce timestamp-only diffs that
    Syncthing flags as `.secrets.sync-conflict-*.baseline` files. Compare
    the would-be JSON to the on-disk JSON ignoring volatile fields, and
    skip the write when they match.
    """
    import tempfile

    volatile_keys = {"generated_at"}

    def _normalize(d: dict) -> dict:
        return {k: v for k, v in d.items() if k not in volatile_keys}

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".baseline", delete=False, dir=baseline_path.parent
    ) as tmp:
        tmp_path = Path(tmp.name)
    try:
        ds_baseline.save_to_file(result_sc, str(tmp_path))
        new_data = json.loads(tmp_path.read_text())
        if baseline_path.exists():
            try:
                old_data = json.loads(baseline_path.read_text())
                if _normalize(old_data) == _normalize(new_data):
                    return
            except (OSError, json.JSONDecodeError):
                pass
        tmp_path.replace(baseline_path)
    finally:
        if tmp_path.exists():
            tmp_path.unlink()


def count_unaudited(baseline_path: Path) -> tuple[int, list[str]]:
    """Return (count, sample) for unaudited (is_secret=null) findings."""
    try:
        data = json.loads(baseline_path.read_text())
    except (OSError, json.JSONDecodeError):
        return 0, []
    results = data.get("results", {})
    sample: list[str] = []
    count = 0
    for filepath, findings in results.items():
        for f in findings:
            if f.get("is_secret") is None:
                count += 1
                if len(sample) < UNAUDITED_SAMPLE_LIMIT:
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
    "reference, then re-scan.\n"
    "For false positives, mark inline with a sentinel comment on the same "
    "line (works in markdown, yaml, code, etc):\n"
    "    <!-- pragma: allowlist secret -->     # markdown / html / xml\n"
    "    # pragma: allowlist secret             # yaml / sh / py\n"
    "    // pragma: allowlist secret            # js / go / c\n"
    "Or batch-audit existing findings in the baseline:\n"
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
    vault_root: str, rel_paths: list[str], literals: list[str]
) -> tuple[int, int, list[str]]:
    """Grep `rel_paths` (vault-relative) for literal occurrences in `literals`.

    Returns `(total_matches, files_with_matches, sample)` where
    `sample` is a list of `path:line_number :: literal` strings
    (paths reported as vault-relative), capped at
    KNOWN_LEAKED_SAMPLE_LIMIT.
    """
    if not rel_paths or not literals:
        return 0, 0, []
    total = 0
    files_hit: set[str] = set()
    sample: list[str] = []
    for rel in rel_paths:
        absolute = os.path.join(vault_root, rel)
        try:
            with open(absolute, "r", encoding="utf-8", errors="replace") as f:
                for lineno, line in enumerate(f, start=1):
                    for literal in literals:
                        if literal in line:
                            total += 1
                            files_hit.add(rel)
                            if len(sample) < KNOWN_LEAKED_SAMPLE_LIMIT:
                                sample.append(f"{rel}:{lineno} :: {literal}")
        except OSError:
            continue
    return total, len(files_hit), sample


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Scan vault for leaked secrets (Stop hook by default; "
                    "--manual for slash-command invocation)."
    )
    parser.add_argument(
        "--manual", action="store_true",
        help="Manual run: skip cooldown + stdin payload; print findings to stdout.",
    )
    parser.add_argument(
        "--full", action="store_true",
        help="Manual mode: delete the baseline first to force a full rescan.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv if argv is not None else sys.argv[1:])

    if not is_in_vault(os.getcwd()):
        if args.manual:
            print(
                "Not inside a configured vault root. "
                "Configure ~/.config/obsidian-knowledge/vaults.yaml.",
                file=sys.stderr,
            )
            sys.exit(1)
        sys.exit(0)

    if not args.manual:
        payload = read_input()
        if in_cooldown(payload, marker_basename="secrets-scan"):
            sys.exit(0)

    vault_root = find_containing_vault(os.getcwd(), load_vault_roots())
    if not vault_root:
        if args.manual:
            print("cwd not inside any configured vault.", file=sys.stderr)
            sys.exit(1)
        sys.exit(0)

    baseline_path = Path(vault_root) / BASELINE_FILENAME
    if args.manual and args.full and baseline_path.exists():
        baseline_path.unlink()

    all_paths = find_files(vault_root)
    # Baseline mtime is the vault-global "last scanned" signal — using
    # the per-session cooldown marker here would force a full scan in
    # every new session.
    if not baseline_path.exists():
        scan_paths = all_paths
    else:
        scan_paths = find_files(vault_root, since_mtime=baseline_path.stat().st_mtime)
        # Even with no rescans, we still call run_scan so deletions get
        # pruned from the baseline.

    run_scan(baseline_path, vault_root, scan_paths, all_paths)
    count, sample = count_unaudited(baseline_path)

    # Known-leaked literals: walk every file in the vault, not just
    # mtime-changed ones, so a literal added to .secrets.known-leaked
    # surfaces existing occurrences immediately.
    literals = load_known_leaked(vault_root)
    if literals:
        leaked_count, leaked_files, leaked_sample = scan_known_leaked(
            vault_root, all_paths, literals
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

    if args.manual:
        if not messages:
            print(
                f"detect-secrets: clean. Scanned {len(scan_paths)} file(s) "
                f"out of {len(all_paths)} in vault."
            )
            sys.exit(0)
        print("\n\n".join(messages))
        sys.exit(0)

    if not messages:
        sys.exit(0)
    emit_block("\n\n".join(messages))


if __name__ == "__main__":
    main()
