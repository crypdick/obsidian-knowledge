#!/usr/bin/env python3
"""
PreToolUse hook: protect Obsidian vault integrity.

Ships with the obsidian-knowledge plugin. Provides:
- Read-only _sources/ directories (irreplaceable originals like tax records,
  legal filings, vital docs). Agents can read but not write.
- Guards against recursive rm/mv on vault paths.

Escape hatch: prefix Bash commands with I_AM_BEING_CAREFUL=1 to bypass.
Write/Edit to _sources/ has no inline bypass — use Bash with the escape hatch.
"""

import json
import os
import re
import sys

ESCAPE_HATCH = "I_AM_BEING_CAREFUL=1"
PROTECTED_DIRS = ["_sources"]  # folder names that are read-only to the agent


# ── Helpers ──────────────────────────────────────────────────────


def find_vault_root(path: str) -> str | None:
    """Walk up from path looking for .obsidian/ directory (Obsidian's vault marker)."""
    d = os.path.dirname(path) if not os.path.isdir(path) else path
    while d != "/":
        if os.path.isdir(os.path.join(d, ".obsidian")):
            return d
        d = os.path.dirname(d)
    return None


def deny(rule: str, message: str, hint: str = "") -> str:
    # NOTE TO AI AGENT: You MUST NOT prepend I_AM_BEING_CAREFUL=1 yourself.
    # Show this deny message to the user and wait for them to explicitly say
    # "use the escape hatch" or "I confirm". Self-authorizing the escape hatch
    # defeats the entire purpose of this safety system.
    escape_warning = (
        f"\n\n>>> AGENT: DO NOT bypass this by prepending {ESCAPE_HATCH} yourself. <<<"
        "\n>>> Show this BLOCKED message to the user verbatim and ask them to confirm. <<<"
        "\n>>> The escape hatch exists for the HUMAN to authorize, not for you to self-authorize. <<<"
        f"\n>>> If the user confirms, re-run with {ESCAPE_HATCH} prepended. <<<"
    )
    if not hint:
        hint = ""
    return f"BLOCKED [{rule}]: {message} {hint}{escape_warning}"


def path_hits_protected_dir(path: str) -> bool:
    return any(
        f"/{d}/" in path or path.rstrip("/").endswith(f"/{d}")
        for d in PROTECTED_DIRS
    )


# ── Rules ────────────────────────────────────────────────────────


def protected_dirs_file(tool_name: str, tool_input: dict) -> str | None:
    """Block Write/Edit to _sources/ directories inside any Obsidian vault."""
    if tool_name not in ("Write", "Edit"):
        return None
    file_path = tool_input.get("file_path", "")
    if not path_hits_protected_dir(file_path):
        return None
    if find_vault_root(file_path):
        dirs = ", ".join(PROTECTED_DIRS)
        return deny(
            "protected-dir",
            f"Cannot modify files in protected directories ({dirs}). These contain irreplaceable originals.",
            f"To modify, use Bash with {ESCAPE_HATCH} after user confirms.",
        )
    return None


def protected_dirs_bash(tool_name: str, tool_input: dict) -> str | None:
    """Block Bash write operations targeting _sources/ paths."""
    if tool_name != "Bash":
        return None
    command = tool_input.get("command", "")
    if not any(d in command for d in PROTECTED_DIRS):
        return None
    write_patterns = [
        r"\brm\b",
        r"\bmv\b",
        r"\brmdir\b",
        r"\bunlink\b",
        r">\s*\S*_sources",
        r">>\s*\S*_sources",
        r"\bsed\b.*-i",
        r"\bchmod\b",
        r"\bchown\b",
        r"\btruncate\b",
        r"\bshred\b",
    ]
    if any(re.search(p, command) for p in write_patterns):
        dirs = ", ".join(PROTECTED_DIRS)
        return deny(
            "protected-dir-bash",
            f"Bash command would modify files in a protected directory ({dirs}). These contain irreplaceable originals.",
        )
    return None


def destructive_vault_ops(tool_name: str, tool_input: dict) -> str | None:
    """Block recursive rm/mv on paths that appear to be inside an Obsidian vault."""
    if tool_name != "Bash":
        return None
    command = tool_input.get("command", "")
    # Case-insensitive check for "obsidian" anywhere in the command.
    # Broad by design: false-positives are cheap (just requires the escape
    # hatch), false-negatives could mean data loss.
    if not re.search(r"obsidian", command, re.IGNORECASE):
        return None
    if re.search(r"\brm\s+.*-[a-z]*[rR]", command):
        return deny(
            "destructive-rm",
            "Recursive rm on a path that appears to be in an Obsidian vault.",
        )
    if re.search(r"\bmv\b", command):
        return deny(
            "destructive-mv",
            "mv on a path that appears to be in an Obsidian vault. This could relocate or overwrite irreplaceable data.",
        )
    return None


# ── Registry ─────────────────────────────────────────────────────

RULES = [
    protected_dirs_file,
    protected_dirs_bash,
    destructive_vault_ops,
]


# ── Main ─────────────────────────────────────────────────────────


def main():
    try:
        input_data = json.load(sys.stdin)
    except json.JSONDecodeError:
        sys.exit(0)  # malformed input — fail open

    tool_name = input_data.get("tool_name", "")
    tool_input = input_data.get("tool_input", {})

    # Global escape hatch (Bash only)
    if tool_name == "Bash" and ESCAPE_HATCH in tool_input.get("command", ""):
        sys.exit(0)

    for rule in RULES:
        reason = rule(tool_name, tool_input)
        if reason:
            json.dump(
                {
                    "hookSpecificOutput": {
                        "hookEventName": "PreToolUse",
                        "permissionDecision": "deny",
                        "permissionDecisionReason": reason,
                    }
                },
                sys.stdout,
            )
            return

    sys.exit(0)


if __name__ == "__main__":
    main()
