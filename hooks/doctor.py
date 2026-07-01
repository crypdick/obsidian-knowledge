#!/usr/bin/env python3
"""
SessionStart hook: the vault doctor.

Runs once at session start when cwd is inside a configured vault.
Three passes:
- Pass A: count `- [ ]` entries in Utility/obsidian-knowledge/needs-attention.md
- Pass B: walk the vault (skip dotfolders and _sources/) and count
  convention violations using the shared patterns module
- Pass C: probe the local search model so the agent knows whether
  obsidian-knowledge search is degraded. Cached for 24h in
  <vault>/.config/obsidian-knowledge/cache/
  doctor-ollama.json to avoid noise on repeat sessions.

Prints a one-line digest if any count is > 0 OR Ollama is degraded, else silent.

Read-only — never writes to needs-attention.md. Vault-organizer is
the sole writer; run it to persist findings.
"""

import json
import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from hookslib.patterns import (  # noqa: E402
    DATE_PREFIX_RE,
    find_wikilink_ext_violations,
    is_in_dated_folder,
    parse_frontmatter,
)
from hookslib.stop_hook import session_debounce  # noqa: E402
from hookslib.vault_config import load_vault_roots  # noqa: E402
from hookslib.vault_policy import find_containing_vault  # noqa: E402

SKIP_DIRS = {".obsidian", ".config", ".git", ".trash", ".claude", "_sources"}


def count_needs_attention(vault_root: str) -> int:
    path = os.path.join(vault_root, "Utility", "obsidian-knowledge", "needs-attention.md")
    if not os.path.exists(path):
        return 0
    with open(path, encoding="utf-8") as f:
        content = f.read()
    return len(re.findall(r"^- \[ \]", content, re.MULTILINE))


def iter_vault_md_files(vault_root: str):
    for root, dirs, files in os.walk(vault_root):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
        for name in files:
            if name.endswith(".md"):
                yield os.path.join(root, name)


def scan_vault(vault_root: str) -> dict[str, int]:
    wikilink_ext = 0
    undated = 0
    yaml_err = 0
    for path in iter_vault_md_files(vault_root):
        rel = os.path.relpath(path, vault_root)
        if is_in_dated_folder(rel):
            basename = os.path.basename(rel)
            if basename != "index.md" and not DATE_PREFIX_RE.match(basename):
                undated += 1
        try:
            with open(path, encoding="utf-8") as f:
                content = f.read()
        except (OSError, UnicodeDecodeError):
            continue
        if find_wikilink_ext_violations(content):
            wikilink_ext += 1
        _, err = parse_frontmatter(content)
        if err:
            yaml_err += 1
    return {
        "wikilink-ext": wikilink_ext,
        "undated-file": undated,
        "yaml-err": yaml_err,
    }


CACHE_TTL_S = 86_400  # 24h


def check_ollama(vault_root: str) -> str | None:
    """Probe Ollama; return a one-line warning if vector search is degraded.

    Returns None if Ollama is healthy or the probe is cached as healthy.
    The probe runs at most once per 24h per vault — degraded results bypass
    the cache so the warning resurfaces every session until fixed.

    Cache lives in the per-host XDG cache directory (same place the embedding
    DB lives) so it is not synced across machines via Syncthing.
    """
    try:
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
        from vault_index.indexer import default_cache_dir  # type: ignore
    except ImportError:
        return None
    cache_dir = str(default_cache_dir(Path(vault_root)))
    cache_path = os.path.join(cache_dir, "doctor-ollama.json")
    now = time.time()
    try:
        with open(cache_path) as f:
            cached = json.load(f)
        if cached.get("ok") and now - cached.get("ts", 0) < CACHE_TTL_S:
            return None
    except (OSError, ValueError):
        pass

    # Defer import so test_doctor.py doesn't need the vault_index package.
    try:
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
        from vault_index.indexer import (  # type: ignore
            DEFAULT_EMBEDDING_API_BASE,
            DEFAULT_EMBEDDING_MODEL,
            _ollama_probe,
        )
    except ImportError:
        return None

    model = os.environ.get("MEMWEAVE_EMBEDDING_MODEL", DEFAULT_EMBEDDING_MODEL)
    api_base = os.environ.get("MEMWEAVE_EMBEDDING_API_BASE", DEFAULT_EMBEDDING_API_BASE)
    ok, msg = _ollama_probe(api_base, model)

    try:
        os.makedirs(cache_dir, exist_ok=True)
        with open(cache_path, "w") as f:
            json.dump({"ok": ok, "msg": msg, "ts": now}, f)
    except OSError:
        pass

    if ok:
        return None
    bare = model.split("/", 1)[1] if "/" in model else model
    return (
        f"obsidian-knowledge search is using basic ranking — {msg}. "
        f"Fix: `ollama serve` + `ollama pull {bare}` for better ranking."
    )


def main() -> None:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except (json.JSONDecodeError, ValueError):
        payload = {}
    if not isinstance(payload, dict):
        payload = {}

    vault_root = find_containing_vault(os.getcwd(), load_vault_roots())
    if not vault_root:
        sys.exit(0)

    # SessionStart fires on startup|resume|compact. Debounce before the
    # full-vault walk so a rapid re-fire (e.g. an auto-compaction loop)
    # doesn't re-scan the vault and re-print the digest back to back.
    if session_debounce(payload, "doctor"):
        sys.exit(0)

    needs_attention = count_needs_attention(vault_root)
    scan = scan_vault(vault_root)
    ollama_msg = check_ollama(vault_root)

    total = needs_attention + sum(scan.values())
    if total == 0 and not ollama_msg:
        sys.exit(0)

    parts = []
    if total:
        parts.append(f"{needs_attention} needs-attention")
        parts += [f"{v} {k}" for k, v in scan.items()]
    if parts:
        print("vault: " + " + ".join(parts) + " — run vault-organizer to review")
    if ollama_msg:
        print(ollama_msg)


if __name__ == "__main__":
    main()
