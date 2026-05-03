#!/usr/bin/env python3
"""
PreToolUse hook: protect Obsidian vault integrity.

Ships with the obsidian-knowledge plugin. Discovers vaults from
~/.config/obsidian-knowledge/vaults.yaml; reads per-vault policy from
each vault's `.claude/obsidian-knowledge.yaml`.

Always-on rules (no per-vault config required):
- Read-only `_sources/` directories (irreplaceable originals like tax
  records, legal filings, vital docs).
- Recursive rm/mv on vault paths flagged for Obsidian-CLI use instead.
- Edits to dg-publish:true files blocked without user confirmation.
- Operational knowledge writes to ~/.claude/projects/*/memory/ blocked.

Per-vault opt-in rules (no-op without config):
- ai_readonly_folders / ai_readonly_root_files — Write, Edit, Bash
  destructive ops blocked on these paths.
- publish_allowlist — `dg-publish: true` only allowed in listed paths.
- generic_filenames — block creation of wikilink-collision-prone names.
- illegal_filename_chars — block creation of files with chars that
  break sync targets.

Escape hatch: prefix Bash commands with I_AM_BEING_CAREFUL=1 to bypass.
Some rules have no escape hatch (wiki-policy, publish-guard) — see deny
messages.
"""

import json
import os
import re
import sys

# Shared with Stop hooks via lib/vault_config.py; per-vault policy via
# lib/vault_policy.py.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib.vault_config import is_in_vault, load_vault_roots  # noqa: E402
from lib.vault_policy import find_containing_vault, load_vault_policy  # noqa: E402

ESCAPE_HATCH = "I_AM_BEING_CAREFUL=1"
PROTECTED_DIRS = ["_sources"]

VAULT_ROOTS = load_vault_roots()


def command_touches_vault(command: str) -> bool:
    """Return True if the command operates on or from within a vault."""
    if is_in_vault(os.getcwd(), VAULT_ROOTS):
        return True
    return any(
        is_in_vault(token, VAULT_ROOTS)
        for token in command.split()
        if token.startswith(("/", "~"))
    )


# ── Helpers ──────────────────────────────────────────────────────


def deny(rule: str, message: str, hint: str = "", show_escape_hint: bool = True) -> str:
    # NOTE TO AI AGENT: You MUST NOT prepend I_AM_BEING_CAREFUL=1 yourself.
    # Show this deny message to the user and wait for them to explicitly say
    # "use the escape hatch" or "I confirm". Self-authorizing the escape hatch
    # defeats the entire purpose of this safety system.
    escape_warning = (
        f"\n\n>>> AGENT: DO NOT bypass this by prepending {ESCAPE_HATCH} yourself. <<<"
        "\n>>> Show this BLOCKED message to the user verbatim and ask them to confirm. <<<"
        "\n>>> The escape hatch exists for the HUMAN to authorize, not for you to self-authorize. <<<"
        f"\n>>> If the user confirms, re-run with {ESCAPE_HATCH} prepended. <<<"
    ) if show_escape_hint else ""
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
    """Block Write/Edit to _sources/ directories inside any configured vault."""
    if tool_name not in ("Write", "Edit"):
        return None
    file_path = tool_input.get("file_path", "")
    if not path_hits_protected_dir(file_path):
        return None
    if is_in_vault(file_path, VAULT_ROOTS):
        dirs = ", ".join(PROTECTED_DIRS)
        return deny(
            "protected-dir",
            f"Cannot modify files in protected directories ({dirs}). These contain irreplaceable originals.",
            f"To modify, use Bash with {ESCAPE_HATCH} after user confirms.",
        )
    return None


def _bash_write_targets(command: str) -> list:
    """Return paths targeted by destructive operations in a bash command.

    Walks each write operation (redirect, rm/mv/etc., sed -i) and collects
    the actual *target* paths. Avoids the old "any write pattern + zone
    name anywhere in command" trap that false-positived on benign cases
    like `ls _sources/ 2>/dev/null && rm /tmp/x` (rm targets /tmp, not
    _sources, but both tokens were present).
    """
    targets: list = []

    # Stdout/stderr redirects: > target, >> target. Skip /dev/null.
    # Lookbehind avoids matching `<<` heredocs and `2>&1`.
    for m in re.finditer(r'(?<![<>&])>>?\s*(\S+)', command):
        target = m.group(1)
        if target != '/dev/null':
            targets.append(target)

    # Destructive commands: collect non-flag args until next |;& or EOL.
    destructive_cmd = r'\b(?:rm|mv|rmdir|unlink|truncate|shred|chmod|chown)\b'
    for m in re.finditer(rf'{destructive_cmd}([^|;&]*)', command):
        for tok in m.group(1).split():
            if not tok.startswith('-'):
                targets.append(tok)

    # sed -i (in-place edit): file args after -i.
    for m in re.finditer(r'\bsed\b[^|;&]*\s-i\b([^|;&]*)', command):
        for tok in m.group(1).split():
            if tok.startswith(('-', "'", '"')):
                continue
            targets.append(tok)

    return targets


def protected_dirs_bash(tool_name: str, tool_input: dict) -> str | None:
    """Block Bash write operations targeting _sources/ paths."""
    if tool_name != "Bash":
        return None
    command = tool_input.get("command", "")

    for target in _bash_write_targets(command):
        if path_hits_protected_dir(target):
            dirs = ", ".join(PROTECTED_DIRS)
            return deny(
                "protected-dir-bash",
                f"Bash command would modify files in a protected directory ({dirs}). These contain irreplaceable originals.",
            )

    # Safety net: catch `cd /path/_sources && rm foo` — relative-path
    # destructive ops after entering a protected dir. Target-based parsing
    # alone misses this because `foo` doesn't contain `_sources`. Since
    # _sources/ holds irreplaceable originals, defense-in-depth is worth
    # the occasional friction.
    has_destructive = bool(re.search(
        r'\b(?:rm|mv|rmdir|unlink|truncate|shred|chmod|chown|sed\s+-i)\b',
        command,
    ))
    if has_destructive:
        for m in re.finditer(r'\bcd\s+(\S+)', command):
            if path_hits_protected_dir(m.group(1)):
                dirs = ", ".join(PROTECTED_DIRS)
                return deny(
                    "protected-dir-bash",
                    f"Bash command appears to cd into a protected directory ({dirs}) before a destructive op. "
                    "Refusing on the side of caution.",
                )
    return None


def block_published_file_edits(tool_name: str, tool_input: dict) -> str | None:
    """Warn before Edit-ing files already marked dg-publish: true.

    Narrowed to Edit only as of v2.0: for Write, the publish_guard rule
    handles the location-vs-allowlist check on the new content. Edit
    operates on an existing file whose frontmatter we read from disk —
    the warning is "you're about to modify content that's already live
    on the published site."
    """
    if tool_name != "Edit":
        return None
    file_path = tool_input.get("file_path", "")
    if not file_path or not is_in_vault(file_path, VAULT_ROOTS):
        return None
    if not os.path.isfile(file_path):
        return None
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read(1000)
    except (OSError, UnicodeDecodeError):
        return None
    if not content.startswith("---"):
        return None
    end = content.find("---", 3)
    if end == -1:
        return None
    frontmatter = content[3:end]
    if not re.search(r"^dg-publish:\s*true", frontmatter, re.MULTILINE):
        return None
    return deny(
        "published-file",
        f"'{os.path.basename(file_path)}' is published to the website (dg-publish: true). Edits will go live.",
        f"To modify, use Bash with {ESCAPE_HATCH} after the user confirms.",
    )


def _find_path_args(segment: str) -> list[str]:
    """Return the leading PATH args of a `find PATH... [predicates...]` call."""
    m = re.search(r'\bfind\b\s+(.*)', segment)
    if not m:
        return []
    paths: list[str] = []
    for tok in m.group(1).split():
        if tok.startswith(('-', '(', ')', '!')):
            break
        paths.append(tok)
    return paths


def _rsync_dest(segment: str) -> str | None:
    """Return the last positional arg (= destination) of an `rsync ...` call."""
    m = re.search(r'\brsync\b\s+(.*)', segment)
    if not m:
        return None
    positional = [a for a in m.group(1).split() if not a.startswith('-')]
    return positional[-1] if positional else None


def _shred_path_args(segment: str) -> list[str]:
    """Return positional path args of `shred ...`."""
    m = re.search(r'\bshred\b\s+(.*)', segment)
    if not m:
        return []
    return [a for a in m.group(1).split() if not a.startswith('-')]


def destructive_vault_ops(tool_name: str, tool_input: dict) -> str | None:
    """Block destructive ops when the *target* is a vault path (absolute,
    or relative when cwd is inside a vault).

    Covers: recursive `rm`, `mv`, `find -delete`, `find -exec rm`,
    `xargs rm`, `rsync --delete`, `shred`.

    Old implementation fired whenever `mv` or recursive `rm` appeared in
    a command and the command "touched the vault" (cwd in vault, or any
    `/`-prefixed token in vault). That produced false positives like
    `git status && mv /tmp/a /tmp/b` from inside a vault directory: the
    mv has nothing to do with the vault, but the rule blocked because
    cwd was a vault root.
    """
    if tool_name != "Bash":
        return None
    command = tool_input.get("command", "")
    cwd = os.getcwd()
    cwd_in_vault = is_in_vault(cwd, VAULT_ROOTS)

    def target_in_vault(token: str) -> bool:
        if token.startswith(("/", "~")):
            return is_in_vault(token, VAULT_ROOTS)
        # Relative paths are vault paths only if cwd is in a vault.
        return cwd_in_vault

    # Split into statements (`;`, `&&`, `||`), then pipeline segments (`|`).
    statements = re.split(r'&&|\|\||;', command)
    for stmt in statements:
        segments = stmt.split('|')

        for seg in segments:
            # rm / mv
            for m in re.finditer(r'\b(rm|mv)\b([^|;&]*)', seg):
                cmd = m.group(1)
                tokens = m.group(2).split()
                flags = [t for t in tokens if t.startswith("-")]
                paths = [t for t in tokens if not t.startswith("-")]

                if cmd == "rm":
                    if not any(re.search(r"[rR]", f) for f in flags):
                        continue
                    for p in paths:
                        if target_in_vault(p):
                            return deny(
                                "destructive-rm",
                                "Recursive rm on a path that appears to be in an Obsidian vault.",
                            )

                if cmd == "mv":
                    for p in paths:
                        if target_in_vault(p):
                            return deny(
                                "destructive-mv",
                                "mv on a path that appears to be in an Obsidian vault. "
                                "Use the Obsidian CLI for moves to preserve internal links.",
                            )

            # find -delete | find -exec rm
            if re.search(r'\bfind\b', seg) and (
                re.search(r'-delete\b', seg) or re.search(r'-exec\s+rm\b', seg)
            ):
                label = "find -delete" if re.search(r'-delete\b', seg) else "find -exec rm"
                for p in _find_path_args(seg):
                    if target_in_vault(p):
                        return deny(
                            "destructive-find",
                            f"{label} on a path that appears to be in an Obsidian vault.",
                        )

            # rsync --delete
            if re.search(r'\brsync\b', seg) and re.search(r'--delete\b', seg):
                dest = _rsync_dest(seg)
                if dest and target_in_vault(dest):
                    return deny(
                        "destructive-rsync-delete",
                        "rsync --delete with a destination in an Obsidian vault.",
                    )

            # shred
            if re.search(r'\bshred\b', seg):
                for p in _shred_path_args(seg):
                    if target_in_vault(p):
                        return deny(
                            "destructive-shred",
                            "shred on a path that appears to be in an Obsidian vault.",
                        )

        # xargs rm: cross-segment scan within the statement.
        # rm gets its targets from stdin, so check upstream pipe segments
        # (and cwd) for vault-path references.
        for i, seg in enumerate(segments):
            if not (re.search(r'\bxargs\b', seg) and re.search(r'\brm\b', seg)):
                continue
            if cwd_in_vault:
                return deny(
                    "destructive-xargs-rm",
                    "xargs rm in a pipeline rooted in an Obsidian vault (cwd).",
                )
            upstream_tokens = ' '.join(segments[:i]).split()
            for tok in upstream_tokens:
                if tok.startswith(('/', '~')) and is_in_vault(tok, VAULT_ROOTS):
                    return deny(
                        "destructive-xargs-rm",
                        "xargs rm in a pipeline that references an Obsidian vault path.",
                    )

    return None


# ── Per-vault policy rules (opt-in via .claude/obsidian-knowledge.yaml) ──


def _publishable_zone_match(abs_path: str, vault_root: str, policy: dict) -> str | None:
    """Return the offending zone label if `abs_path` is publishable, else None."""
    rel = os.path.relpath(abs_path, vault_root)
    parts = rel.split(os.sep)
    folders = policy.get("ai_readonly_folders", []) or []
    root_files = policy.get("ai_readonly_root_files", []) or []
    if parts and parts[0] in folders:
        return f"{parts[0]}/"
    if len(parts) == 1 and rel in root_files:
        return rel
    return None


def ai_readonly_file(tool_name: str, tool_input: dict) -> str | None:
    """Block Write/Edit on publishable-zone paths (Zone 1)."""
    if tool_name not in ("Write", "Edit"):
        return None
    file_path = tool_input.get("file_path", "")
    if not file_path:
        return None
    vault_root = find_containing_vault(file_path, VAULT_ROOTS)
    if not vault_root:
        return None
    policy = load_vault_policy(vault_root)
    abs_path = os.path.abspath(os.path.expanduser(file_path))
    label = _publishable_zone_match(abs_path, vault_root, policy)
    if not label:
        return None
    return deny(
        "ai-readonly",
        f"Cannot modify files in the publishable zone ({label}). "
        "These are Digital Garden content managed by the user.",
    )


def ai_readonly_bash(tool_name: str, tool_input: dict) -> str | None:
    """Block destructive Bash ops targeting publishable-zone paths."""
    if tool_name != "Bash":
        return None
    command = tool_input.get("command", "")
    cwd = os.getcwd()
    cwd_vault = find_containing_vault(cwd, VAULT_ROOTS)
    # Anchor on cwd-vault for relative-path resolution; otherwise look for
    # any vault root mentioned in the command's targets.
    for target in _bash_write_targets(command):
        if target.startswith(("/", "~")):
            abs_target = os.path.abspath(os.path.expanduser(target))
        else:
            if not cwd_vault:
                continue  # relative path outside any vault — skip
            abs_target = os.path.abspath(os.path.join(cwd, target))
        target_vault = find_containing_vault(abs_target, VAULT_ROOTS)
        if not target_vault:
            continue
        policy = load_vault_policy(target_vault)
        label = _publishable_zone_match(abs_target, target_vault, policy)
        if label:
            return deny(
                "ai-readonly-bash",
                f"Bash command would modify files in the publishable zone ({label}). "
                "These are Digital Garden content managed by the user.",
            )
    return None


def _matches_publish_allowlist(rel_path: str, allowlist: list) -> bool:
    for entry in allowlist:
        if entry.endswith("/"):
            stripped = entry.rstrip("/")
            if rel_path == stripped or rel_path.startswith(entry):
                return True
        elif rel_path == entry:
            return True
    return False


def publish_guard(tool_name: str, tool_input: dict) -> str | None:
    """Block setting `dg-publish: true` outside the publish allowlist."""
    if tool_name not in ("Write", "Edit"):
        return None
    content = (
        tool_input.get("content", "")
        if tool_name == "Write"
        else tool_input.get("new_string", "")
    )
    if "dg-publish" not in content:
        return None
    if not re.search(r"^\s*dg-publish:\s*true\s*$", content, re.MULTILINE):
        return None
    file_path = tool_input.get("file_path", "")
    if not file_path:
        return None
    vault_root = find_containing_vault(file_path, VAULT_ROOTS)
    if not vault_root:
        return None
    policy = load_vault_policy(vault_root)
    allowlist = policy.get("publish_allowlist", []) or []
    if not allowlist:
        return None
    rel = os.path.relpath(os.path.abspath(file_path), vault_root)
    if _matches_publish_allowlist(rel, allowlist):
        return None
    return deny(
        "publish-guard",
        f"Cannot set dg-publish: true on {rel}. Publishing is only allowed in "
        "paths listed in publish_allowlist (.claude/obsidian-knowledge.yaml).",
        show_escape_hint=False,
    )


def generic_filename_guard(tool_name: str, tool_input: dict) -> str | None:
    """Block creation of generic basenames that collide on Obsidian wikilinks."""
    if tool_name != "Write":
        return None
    file_path = tool_input.get("file_path", "")
    if not file_path:
        return None
    vault_root = find_containing_vault(file_path, VAULT_ROOTS)
    if not vault_root:
        return None
    if os.path.exists(file_path):
        return None  # overwriting an existing file
    policy = load_vault_policy(vault_root)
    generics = {g.lower() for g in (policy.get("generic_filenames", []) or [])}
    if not generics:
        return None
    basename = os.path.basename(file_path)
    if basename.lower() not in generics:
        return None
    if basename.lower() == "index.md":
        return None
    stem = os.path.splitext(basename)[0]
    return deny(
        "generic-filename",
        f"Refusing to create '{basename}'. Obsidian resolves wikilinks by "
        f"basename, so this would collide with every other '{basename}' across "
        f"the vault. Prefix with context — e.g., '{stem}-<context>.md'. "
        "(index.md is the only exception; it's disambiguated via [[folder/index]].)",
        show_escape_hint=False,
    )


def illegal_filename_guard(tool_name: str, tool_input: dict) -> str | None:
    """Block creation of files with chars illegal on any sync target."""
    if tool_name != "Write":
        return None
    file_path = tool_input.get("file_path", "")
    if not file_path:
        return None
    vault_root = find_containing_vault(file_path, VAULT_ROOTS)
    if not vault_root:
        return None
    if os.path.exists(file_path):
        return None
    policy = load_vault_policy(vault_root)
    chars = policy.get("illegal_filename_chars", []) or []
    if not chars:
        return None
    illegal_re = re.compile("[" + re.escape("".join(chars)) + "]")
    basename = os.path.basename(file_path)
    bad = illegal_re.findall(basename)
    if not bad:
        return None
    bad_chars = " ".join(sorted(set(bad)))
    safe_name = illegal_re.sub("-", basename)
    return deny(
        "illegal-filename",
        f"Refusing to create '{basename}'. Characters {bad_chars} are illegal "
        "on one or more sync targets (Linux, macOS, Android) and will prevent "
        f"Syncthing from syncing. Suggested alternative: '{safe_name}'",
        show_escape_hint=False,
    )


def block_memory_file_creation(tool_name: str, tool_input: dict) -> str | None:
    """Redirect operational knowledge from agent auto-memory to the Obsidian wiki.

    Blocks Write/Edit to feedback_*.md, project_*.md, reference_*.md in any
    ~/.claude/projects/*/memory/ directory. MEMORY.md (the pointer index) and
    user_*.md (user-profile facts) are allowed through.
    """
    if tool_name not in ("Write", "Edit"):
        return None
    file_path = tool_input.get("file_path", "")
    if not re.search(r"/\.claude/projects/[^/]+/memory/", file_path):
        return None
    basename = os.path.basename(file_path)
    blocked_prefixes = ("feedback_", "project_", "reference_")
    if not any(basename.startswith(p) for p in blocked_prefixes):
        return None
    if not VAULT_ROOTS:
        vault_lines = "  (no vaults configured in ~/.config/obsidian-knowledge/vaults.yaml)"
    elif len(VAULT_ROOTS) == 1:
        vault_lines = f"  Vault: {VAULT_ROOTS[0]}"
    else:
        vault_lines = "  Vaults:\n" + "\n".join(f"    - {r}" for r in VAULT_ROOTS)
    return deny(
        "wiki-policy",
        f"Writing '{basename}' to agent auto-memory is not permitted. "
        "Auto-memory is a per-project silo — invisible to other sessions, other tools, and vault search.",
        hint=(
            "\n\nWhere to write instead:\n"
            "  - Behavioral rules (how the agent should act) → CLAUDE.md in the Obsidian vault\n"
            "  - Facts about the world (tools, gotchas, procedures, system state) → wiki/ in the vault\n"
            "  - MEMORY.md is the only file permitted here — use it only as a pointer to vault locations.\n"
            f"\n{vault_lines}\n"
            "\n(The I_AM_BEING_CAREFUL=1 escape hatch does not apply to this rule — there is no bypass.)"
        ),
        show_escape_hint=False,
    )


# ── Registry ─────────────────────────────────────────────────────

RULES = [
    # Order matters: path-specific rules first, then content/destination,
    # then existing-state warnings. First match wins.
    protected_dirs_file,
    protected_dirs_bash,
    ai_readonly_file,
    ai_readonly_bash,
    destructive_vault_ops,
    publish_guard,
    block_published_file_edits,
    generic_filename_guard,
    illegal_filename_guard,
    block_memory_file_creation,
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
