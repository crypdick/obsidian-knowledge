#!/usr/bin/env python3
# allow: file-length  (vault-write guard; decomposition tracked in docs/QUALITY.md)
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
import shlex
import sys
from collections.abc import Callable
from typing import Any

# Shared with Stop hooks via lib/vault_config.py; per-vault policy via
# lib/vault_policy.py.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hookslib.repo_memory import resolve_target
from hookslib.vault_config import is_in_vault, load_vault_roots
from hookslib.vault_policy import find_containing_vault, load_vault_policy

ESCAPE_HATCH = "I_AM_BEING_CAREFUL=1"
PROTECTED_DIRS = ["_sources"]

VAULT_ROOTS = load_vault_roots()


def command_touches_vault(command: str) -> bool:
    """Return True if the command operates on or from within a vault."""
    if is_in_vault(os.getcwd(), VAULT_ROOTS):
        return True
    return any(is_in_vault(token, VAULT_ROOTS) for token in command.split() if token.startswith(("/", "~")))


# ── Helpers ──────────────────────────────────────────────────────


def deny(rule: str, message: str, hint: str = "", show_escape_hint: bool = True) -> str:
    # NOTE TO AI AGENT: You MUST NOT prepend I_AM_BEING_CAREFUL=1 yourself.
    # Show this deny message to the user and wait for them to explicitly say
    # "use the escape hatch" or "I confirm". Self-authorizing the escape hatch
    # defeats the entire purpose of this safety system.
    escape_warning = (
        (
            f"\n\n>>> AGENT: DO NOT bypass this by prepending {ESCAPE_HATCH} yourself. <<<"
            "\n>>> Show this BLOCKED message to the user verbatim and ask them to confirm. <<<"
            "\n>>> The escape hatch exists for the HUMAN to authorize, not for you to self-authorize. <<<"
            f"\n>>> If the user confirms, re-run with {ESCAPE_HATCH} prepended. <<<"
        )
        if show_escape_hint
        else ""
    )
    if not hint:
        hint = ""
    return f"BLOCKED [{rule}]: {message} {hint}{escape_warning}"


def path_hits_protected_dir(path: str) -> bool:
    return any(f"/{d}/" in path or path.rstrip("/").endswith(f"/{d}") for d in PROTECTED_DIRS)


# ── Rules ────────────────────────────────────────────────────────


def protected_dirs_file(tool_name: str, tool_input: dict[str, Any]) -> str | None:
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


_HEREDOC_RE = re.compile(r"<<(?P<tabs>-)?\s*(?P<quote>['\"]?)(?P<delimiter>[A-Za-z_][A-Za-z0-9_]*)(?P=quote)")
_ASSIGNMENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_COMMAND_WRAPPERS = {"command", "exec", "nohup"}
_PRIVILEGE_WRAPPERS = {"doas", "sudo"}
_WRAPPER_VALUE_FLAGS = {"-g", "--group", "-h", "--host", "-u", "--user"}
_REDIRECTIONS = {"<", "<<", "<<<", ">", ">>", "<>", "<&", ">&"}


def _without_heredoc_bodies(command: str) -> str:
    """Remove heredoc payloads, which are data or input to another process."""
    kept: list[str] = []
    pending: list[tuple[str, bool]] = []
    for line in command.splitlines():
        if pending:
            delimiter, strip_tabs = pending[0]
            candidate = line.lstrip("\t") if strip_tabs else line
            if candidate == delimiter:
                pending.pop(0)
            continue
        kept.append(line)
        pending.extend(
            (match.group("delimiter"), match.group("tabs") == "-") for match in _HEREDOC_RE.finditer(line)
        )
    # ponytail: heredoc payloads are opaque input; use a shell AST if local
    # shell-heredoc enforcement becomes necessary.
    return "\n".join(kept)


def _shell_pipelines(command: str) -> list[list[list[str]]]:
    """Tokenize local shell commands while preserving quoted argument text."""
    lexer = shlex.shlex(
        _without_heredoc_bodies(command),
        posix=True,
        punctuation_chars="|&;<>\n",
    )
    lexer.whitespace = " \t\r"
    lexer.whitespace_split = True
    lexer.commenters = ""
    try:
        tokens = list(lexer)
    except ValueError:
        return []

    pipelines: list[list[list[str]]] = []
    pipeline: list[list[str]] = []
    simple_command: list[str] = []

    def finish_command() -> None:
        if simple_command:
            pipeline.append(simple_command.copy())
            simple_command.clear()

    def finish_pipeline() -> None:
        finish_command()
        if pipeline:
            pipelines.append(pipeline.copy())
            pipeline.clear()

    for token in tokens:
        if token == "|":
            finish_command()
        elif token in {"&", "&&", "||", ";", "\n"}:
            finish_pipeline()
        else:
            simple_command.append(token)
    finish_pipeline()
    return pipelines


def _command_parts(tokens: list[str]) -> tuple[str, list[str]]:
    """Return the executable basename and args for one simple command."""
    index = 0
    while index < len(tokens) and _ASSIGNMENT_RE.match(tokens[index]):
        index += 1

    while index < len(tokens):
        executable = os.path.basename(tokens[index])
        if executable == "env":
            index += 1
            while index < len(tokens) and (
                tokens[index].startswith("-") or _ASSIGNMENT_RE.match(tokens[index])
            ):
                index += 1
            continue
        if executable in _COMMAND_WRAPPERS:
            index += 1
            while index < len(tokens) and tokens[index].startswith("-"):
                index += 1
            continue
        if executable in _PRIVILEGE_WRAPPERS:
            index += 1
            while index < len(tokens) and tokens[index].startswith("-"):
                flag = tokens[index]
                index += 1
                if flag in _WRAPPER_VALUE_FLAGS and index < len(tokens):
                    index += 1
            continue
        return executable, tokens[index + 1 :]
    return "", []


def _flags_and_paths(args: list[str]) -> tuple[list[str], list[str]]:
    """Separate flags from positional paths, excluding redirection targets."""
    flags: list[str] = []
    paths: list[str] = []
    end_options = False
    index = 0
    while index < len(args):
        token = args[index]
        if token in _REDIRECTIONS:
            index += 2
            continue
        if token == "--":
            end_options = True
        elif not end_options and token.startswith("-"):
            flags.append(token)
        else:
            paths.append(token)
        index += 1
    return flags, paths


def _obsidian_knowledge_write_target(executable: str, args: list[str]) -> str | None:
    """Resolve an `obsidian-knowledge write` path for existing Bash guards."""
    if executable != "obsidian-knowledge" or not args or args[0] != "write":
        return None

    relative_path: str | None = None
    explicit_vault: str | None = None
    index = 1
    while index < len(args):
        token = args[index]
        if token == "--vault" and index + 1 < len(args):
            explicit_vault = args[index + 1]
            index += 2
            continue
        if token.startswith("--vault="):
            explicit_vault = token.split("=", 1)[1]
        elif not token.startswith("-") and relative_path is None:
            relative_path = token
        index += 1
    if relative_path is None:
        return None

    vault = explicit_vault or find_containing_vault(os.getcwd(), VAULT_ROOTS)
    if vault is None and VAULT_ROOTS:
        vault = VAULT_ROOTS[0]
    return os.path.join(vault, relative_path) if vault else None


def _bash_write_targets(command: str) -> list[str]:
    """Return paths targeted by actual local write commands."""
    targets: list[str] = []
    destructive = {"chmod", "chown", "mv", "rm", "rmdir", "shred", "truncate", "unlink"}
    for pipeline in _shell_pipelines(command):
        for tokens in pipeline:
            for index, token in enumerate(tokens[:-1]):
                if token in {">", ">>"} and tokens[index + 1] != "/dev/null":
                    targets.append(tokens[index + 1])

            executable, args = _command_parts(tokens)
            flags, paths = _flags_and_paths(args)
            cli_target = _obsidian_knowledge_write_target(executable, args)
            if cli_target is not None:
                targets.append(cli_target)
            elif executable in destructive:
                targets.extend(paths)
            elif executable == "sed" and any("i" in flag.lstrip("-") for flag in flags):
                targets.extend(paths[1:])
    return targets


def protected_dirs_bash(tool_name: str, tool_input: dict[str, Any]) -> str | None:
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
    commands = [_command_parts(tokens) for pipeline in _shell_pipelines(command) for tokens in pipeline]
    destructive = {"chmod", "chown", "mv", "rm", "rmdir", "shred", "truncate", "unlink"}
    has_destructive = any(
        executable in destructive
        or (executable == "sed" and any("i" in flag.lstrip("-") for flag in args if flag.startswith("-")))
        for executable, args in commands
    )
    if has_destructive:
        for executable, args in commands:
            if executable == "cd" and args and path_hits_protected_dir(args[0]):
                dirs = ", ".join(PROTECTED_DIRS)
                return deny(
                    "protected-dir-bash",
                    f"Bash command appears to cd into a protected directory ({dirs}) before a destructive op. "
                    "Refusing on the side of caution.",
                )
    return None


def block_published_file_edits(tool_name: str, tool_input: dict[str, Any]) -> str | None:
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
        with open(file_path, encoding="utf-8") as f:
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


def _check_rm_mv(
    executable: str,
    args: list[str],
    target_in_vault: Callable[[str], bool],
) -> str | None:
    """Block recursive `rm` or any `mv` whose target is a vault path."""
    if executable not in {"rm", "mv"}:
        return None
    flags, paths = _flags_and_paths(args)
    if executable == "rm":
        if not any(flag == "--recursive" or re.search(r"[rR]", flag.lstrip("-")) for flag in flags):
            return None
        if any(target_in_vault(path) for path in paths):
            return deny(
                "destructive-rm",
                "Recursive rm on a path that appears to be in an Obsidian vault.",
            )
    elif any(target_in_vault(path) for path in paths):
        return deny(
            "destructive-mv",
            "mv on a path that appears to be in an Obsidian vault. "
            "Use the Obsidian CLI for moves to preserve internal links.",
        )
    return None


def _check_find_delete(
    executable: str,
    args: list[str],
    target_in_vault: Callable[[str], bool],
) -> str | None:
    """Block `find -delete` / `find -exec rm` whose path arg is a vault path."""
    if executable != "find":
        return None
    has_delete = "-delete" in args
    has_exec_rm = any(
        token == "-exec" and index + 1 < len(args) and os.path.basename(args[index + 1]) == "rm"
        for index, token in enumerate(args)
    )
    if not (has_delete or has_exec_rm):
        return None
    paths: list[str] = []
    for token in args:
        if token.startswith(("-", "(", ")", "!")):
            break
        paths.append(token)
    if any(target_in_vault(path) for path in (paths or ["."])):
        label = "find -delete" if has_delete else "find -exec rm"
        return deny(
            "destructive-find",
            f"{label} on a path that appears to be in an Obsidian vault.",
        )
    return None


def _check_rsync_delete(
    executable: str,
    args: list[str],
    target_in_vault: Callable[[str], bool],
) -> str | None:
    """Block `rsync --delete` whose destination is a vault path."""
    if executable != "rsync" or not any(flag.startswith("--delete") for flag in args):
        return None
    _flags, paths = _flags_and_paths(args)
    if paths and target_in_vault(paths[-1]):
        return deny(
            "destructive-rsync-delete",
            "rsync --delete with a destination in an Obsidian vault.",
        )
    return None


def _check_shred(
    executable: str,
    args: list[str],
    target_in_vault: Callable[[str], bool],
) -> str | None:
    """Block `shred` whose path arg is a vault path."""
    if executable != "shred":
        return None
    _flags, paths = _flags_and_paths(args)
    if any(target_in_vault(path) for path in paths):
        return deny(
            "destructive-shred",
            "shred on a path that appears to be in an Obsidian vault.",
        )
    return None


def _xargs_executable(args: list[str]) -> str:
    """Return the executable selected by xargs, excluding its own options."""
    options_with_values = {"-E", "-I", "-L", "-P", "-S", "-a", "-d", "-n", "-s"}
    index = 0
    while index < len(args):
        token = args[index]
        if token == "--":
            index += 1
            break
        if not token.startswith("-"):
            break
        index += 2 if token in options_with_values else 1
    return os.path.basename(args[index]) if index < len(args) else ""


def _check_xargs_rm(pipeline: list[list[str]], cwd_in_vault: bool) -> str | None:
    """Block `xargs rm` fed by a pipeline rooted in / referencing a vault.

    rm gets its targets from stdin, so check upstream pipe segments
    (and cwd) for vault-path references.
    """
    for index, tokens in enumerate(pipeline):
        executable, args = _command_parts(tokens)
        if executable != "xargs" or _xargs_executable(args) != "rm":
            continue
        if cwd_in_vault:
            return deny(
                "destructive-xargs-rm",
                "xargs rm in a pipeline rooted in an Obsidian vault (cwd).",
            )
        for upstream in pipeline[:index]:
            for token in upstream:
                if token.startswith(("/", "~")) and is_in_vault(token, VAULT_ROOTS):
                    return deny(
                        "destructive-xargs-rm",
                        "xargs rm in a pipeline that references an Obsidian vault path.",
                    )
    return None


def destructive_vault_ops(tool_name: str, tool_input: dict[str, Any]) -> str | None:
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
        # Only treat as a relative vault path if the token looks like an actual
        # path — not a shell escape char, quote, or pipe fragment.  This prevents
        # false positives when 'mv' appears inside a grep pattern like "mv\|foo":
        # the trailing '\' (before the pipe) would otherwise trigger here.
        if not token or token[0] in ('"', "'", "\\", "|", "&", ";", "<", ">"):
            return False
        return cwd_in_vault

    # Per-command checks, in order; first match wins.
    segment_checks = (_check_rm_mv, _check_find_delete, _check_rsync_delete, _check_shred)

    for pipeline in _shell_pipelines(command):
        for tokens in pipeline:
            executable, args = _command_parts(tokens)
            for check in segment_checks:
                reason = check(executable, args, target_in_vault)
                if reason is not None:
                    return reason

        reason = _check_xargs_rm(pipeline, cwd_in_vault)
        if reason is not None:
            return reason

    return None


# ── Per-vault policy rules (opt-in via .claude/obsidian-knowledge.yaml) ──


def _publishable_zone_match(abs_path: str, vault_root: str, policy: dict[str, Any]) -> str | None:
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


def ai_readonly_file(tool_name: str, tool_input: dict[str, Any]) -> str | None:
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


def ai_readonly_bash(tool_name: str, tool_input: dict[str, Any]) -> str | None:
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


def _matches_publish_allowlist(rel_path: str, allowlist: list[str]) -> bool:
    for entry in allowlist:
        if entry.endswith("/"):
            stripped = entry.rstrip("/")
            if rel_path == stripped or rel_path.startswith(entry):
                return True
        elif rel_path == entry:
            return True
    return False


def publish_guard(tool_name: str, tool_input: dict[str, Any]) -> str | None:
    """Block setting `dg-publish: true` outside the publish allowlist."""
    if tool_name not in ("Write", "Edit"):
        return None
    content = tool_input.get("content", "") if tool_name == "Write" else tool_input.get("new_string", "")
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


def generic_filename_guard(tool_name: str, tool_input: dict[str, Any]) -> str | None:
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


def illegal_filename_guard(tool_name: str, tool_input: dict[str, Any]) -> str | None:
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


def block_memory_file_creation(tool_name: str, tool_input: dict[str, Any]) -> str | None:
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
        target_lines = "  (no vaults configured in ~/.config/obsidian-knowledge/vaults.yaml)"
    else:
        target = resolve_target(os.getcwd())
        if target.kind == "repo":
            scope = f"this repo ({target.owner}/{target.repo})"
        else:
            scope = f"this host ({target.hostname}) — no git remote detected from cwd"
        abs_targets = [f"{root}/wiki/{target.rel_path}/{basename}" for root in VAULT_ROOTS]
        if len(abs_targets) == 1:
            target_lines = f"  Write '{basename}' here instead (scoped to {scope}):\n    {abs_targets[0]}"
        else:
            target_lines = f"  Write '{basename}' to one of these (scoped to {scope}):\n" + "\n".join(
                f"    - {p}" for p in abs_targets
            )
    return deny(
        "wiki-policy",
        f"Writing '{basename}' to agent auto-memory is not permitted. "
        "Auto-memory is a per-project silo — invisible to other sessions, other tools, and vault search.",
        hint=(
            "\n\nWhere to write instead:\n"
            "  - First decide whether the fact is stable, in scope, likely to change future action, "
            "and not already authoritative in code, tracked docs, git, or runtime. If not, write nothing.\n"
            "  - Never persist PIDs, job IDs, transient status, temporary worktrees, routine "
            "commit/test results, or per-cycle handoffs as eager memory.\n"
            "  - Durable behavioral rules + project facts (per-repo or per-host scope) → vault path below\n"
            "  - User-profile / world-knowledge → wiki/ wherever it semantically fits (or CLAUDE.md)\n"
            "  - Search and consolidate before writing; keep vault MEMORY.md a thin current-state index.\n"
            "  - Only MEMORY.md is permitted in ~/.claude/projects/*/memory/; use it as a pointer.\n"
            f"\n{target_lines}\n"
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
