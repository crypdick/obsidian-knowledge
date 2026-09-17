"""Vault policy checker; i-insist owns tool normalization and human approval."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parent))

from hookslib.patterns import (
    DATE_PREFIX_RE,
    find_wikilink_ext_violations,
    is_in_dated_folder,
    parse_frontmatter,
)
from hookslib.shell_guard import destructive_vault_ops, enters_protected_directory, write_targets
from hookslib.vault_config import load_vault_roots
from hookslib.vault_policy import find_containing_vault, load_vault_policy


def absolute_path(value: str) -> str:
    if not Path(value).is_absolute() or "\0" in value:
        raise ValueError("event paths must be absolute and contain no NUL bytes")
    return value


AbsolutePath = Annotated[str, AfterValidator(absolute_path)]


class Change(BaseModel):
    model_config = ConfigDict(strict=True)
    path: AbsolutePath
    operation: Literal["write", "edit", "delete"]
    content: str


class Event(BaseModel):
    model_config = ConfigDict(strict=True)
    kind: Literal["shell", "file_write", "file_edit", "other"]
    cwd: AbsolutePath
    command: str | None = None
    paths: list[AbsolutePath] = []
    changes: list[Change]


RULE_IDS = {
    "protected-dirs",
    "ai-readonly",
    "destructive-ops",
    "published-files",
    "publish-allowlist",
    "generic-filenames",
    "illegal-filenames",
    "memory-routing",
    "wikilinks",
    "dated-filenames",
    "frontmatter",
}


def readonly(path: str, roots: list[str]) -> bool:
    root = find_containing_vault(path, roots)
    if root is None:
        return False
    policy = load_vault_policy(root)
    relative = Path(path).relative_to(root)
    return bool(relative.parts) and (
        relative.parts[0] in (policy.get("ai_readonly_folders") or [])
        or (len(relative.parts) == 1 and relative.name in (policy.get("ai_readonly_root_files") or []))
    )


def published(path: Path) -> bool:
    if not path.is_file():
        return False
    with path.open(encoding="utf-8") as stream:
        content = stream.read(1000)
    if not content.startswith("---"):
        return False
    end = content.find("---", 3)
    return end != -1 and bool(re.search(r"^dg-publish:\s*true", content[3:end], re.MULTILINE))


def file_blocks(name: str, change: Change, roots: list[str]) -> bool:
    path = Path(change.path)
    if name == "memory-routing":
        return bool(re.search(r"/\.claude/projects/[^/]+/memory/", change.path)) and path.name.startswith(
            ("feedback_", "project_", "reference_")
        )
    root = find_containing_vault(change.path, roots)
    if root is None:
        return False
    if name == "protected-dirs":
        return "_sources" in path.parts
    if name == "ai-readonly":
        return readonly(change.path, roots)
    if name == "published-files":
        return change.operation != "write" and published(path)
    if change.operation == "delete":
        return False
    content = change.content
    if name == "wikilinks":
        return bool(find_wikilink_ext_violations(content))
    if name == "frontmatter":
        return parse_frontmatter(content)[1] is not None
    relative = str(path.relative_to(root))
    policy = load_vault_policy(root)
    if name == "publish-allowlist":
        allowlist = policy.get("publish_allowlist") or []
        return bool(
            allowlist and re.search(r"^\s*dg-publish:\s*true\s*$", content, re.MULTILINE)
        ) and not any(
            relative == entry.rstrip("/") or (entry.endswith("/") and relative.startswith(entry))
            for entry in allowlist
        )
    if path.exists():
        return False
    if name == "generic-filenames":
        return path.name.lower() != "index.md" and path.name.lower() in {
            item.lower() for item in (policy.get("generic_filenames") or [])
        }
    if name == "illegal-filenames":
        return any(char in path.name for char in (policy.get("illegal_filename_chars") or []))
    if name == "dated-filenames":
        return (
            is_in_dated_folder(relative) and path.name != "index.md" and not DATE_PREFIX_RE.match(path.name)
        )
    return False


def should_block(name: str, event: Event) -> bool:
    if name not in RULE_IDS:
        raise ValueError(f"unknown rule: {name}")
    roots = load_vault_roots()
    if event.kind == "shell":
        if not event.command:
            raise ValueError("shell event needs command")
        if name == "destructive-ops":
            return destructive_vault_ops(event.command, event.cwd)
        targets = write_targets(event.command, event.cwd)
        if name == "protected-dirs":
            return any("_sources" in Path(path).parts for path in targets) or enters_protected_directory(
                event.command
            )
        return name == "ai-readonly" and any(readonly(path, roots) for path in targets)
    if event.kind == "other":
        return False
    if set(event.paths) != {change.path for change in event.changes} or not event.changes:
        raise ValueError("file event needs a change for every path; upgrade i-insist")
    return any(file_blocks(name, change, roots) for change in event.changes)


def main() -> int:
    try:
        if len(sys.argv) != 2:
            raise ValueError("expected one rule id")
        result = should_block(sys.argv[1], Event.model_validate_json(sys.stdin.read()))
    except (ValidationError, ValueError, OSError) as exc:
        print(f"obsidian-knowledge checker: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
