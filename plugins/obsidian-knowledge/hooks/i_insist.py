"""Run provider-owned vault rules against i-insist's neutral event protocol."""

from __future__ import annotations

import json
import runpy
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent

# NOTE: Rule ids and non-overridable policy are canonical in i-insist.toml.
PROTECTION = {
    "protected-dirs": ("protected_dirs_file", "protected_dirs_bash"),
    "ai-readonly": ("ai_readonly_file", "ai_readonly_bash"),
    "destructive-ops": ("destructive_vault_ops",),
    "published-files": ("block_published_file_edits",),
    "publish-allowlist": ("publish_guard",),
    "generic-filenames": ("generic_filename_guard",),
    "illegal-filenames": ("illegal_filename_guard",),
    "memory-routing": ("block_memory_file_creation",),
}
CONVENTIONS = {"wikilinks", "dated-filenames", "frontmatter"}


def file_inputs(event: dict[str, Any]) -> list[dict[str, Any]]:
    """Adapt file content shapes; normalized paths remain authoritative."""
    native = event.get("tool_input", {})
    arguments = native if isinstance(native, dict) else {}
    content = arguments.get("content", arguments.get("new_string", arguments.get("new_source", "")))
    edits = arguments.get("edits")
    if isinstance(edits, list):
        content = "\n".join(edit.get("new_string", "") for edit in edits if isinstance(edit, dict))
    patch = native if isinstance(native, str) else arguments.get("patch", arguments.get("command"))
    patch_contents: dict[str, list[str]] = {}
    if isinstance(patch, str) and patch.startswith("*** Begin Patch"):
        target = ""
        for line in patch.splitlines():
            if line.startswith(("*** Add File: ", "*** Update File: ", "*** Delete File: ", "*** Move to: ")):
                target = str((Path(event["cwd"]) / line.split(": ", 1)[1]).resolve())
                patch_contents.setdefault(target, [])
            elif line.startswith("+") and target:
                patch_contents[target].append(line[1:])
    if not isinstance(content, str):
        raise ValueError("file content must be text")
    return [
        {
            "file_path": str((Path(event["cwd"]) / path).resolve()),
            "cwd": event["cwd"],
            "content": "\n".join(patch_contents.get(path, [])) if patch_contents else content,
            "new_string": "\n".join(patch_contents.get(path, [])) if patch_contents else content,
        }
        for path in event["paths"]
    ]


def should_block(name: str, event: object) -> bool:
    """Return a boolean only; messages and approval belong to i-insist."""
    if name not in PROTECTION and name not in CONVENTIONS:
        raise ValueError(f"unknown rule: {name}")
    if not isinstance(event, dict) or event.get("kind") not in ("shell", "file_write", "file_edit", "other"):
        raise ValueError("event needs a valid kind")
    cwd = event.get("cwd")
    if not isinstance(cwd, str) or not Path(cwd).is_absolute():
        raise ValueError("event needs an absolute cwd")
    kind = event["kind"]
    if kind == "other":
        return False
    if kind == "shell":
        if not isinstance(event.get("command"), str):
            raise ValueError("shell event needs command")
        inputs = [{"command": event["command"], "cwd": cwd}]
        tool = "Bash"
    else:
        paths = event.get("paths")
        if not isinstance(paths, list) or any(not isinstance(p, str) or not p for p in paths):
            raise ValueError("file event needs paths")
        inputs = file_inputs(event)
        tool = "Write" if kind == "file_write" else "Edit"
    if name in PROTECTION:
        policy = runpy.run_path(str(ROOT / "protect-vault.py"))
        for data in inputs:
            # Added patch paths and renamed destinations also create files.
            operation = "Write" if tool == "Edit" and not Path(data["file_path"]).exists() else tool
            if any(policy[rule](operation, data) is not None for rule in PROTECTION[name]):
                return True
        return False
    return tool != "Bash" and conventions_block(name, inputs)


def conventions_block(name: str, inputs: list[dict[str, Any]]) -> bool:
    policy = runpy.run_path(str(ROOT / "enforce-conventions.py"))
    roots = policy["load_vault_roots"]()
    for data in inputs:
        root = policy["find_containing_vault"](data["file_path"], roots)
        if not root:
            continue
        if name == "dated-filenames":
            reason = policy["check_dated_filename"]("Write", data["file_path"], root)
        elif name == "wikilinks":
            reason = policy["check_wikilink_ext"](data["content"])
        else:
            reason = policy["check_frontmatter"](data["content"])
        if reason is not None:
            return True
    return False


def main() -> int:
    try:
        if len(sys.argv) != 2:
            raise ValueError("expected one rule id")
        result = should_block(sys.argv[1], json.load(sys.stdin))
    except (ValueError, TypeError, OSError) as exc:
        print(f"obsidian-knowledge checker: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
