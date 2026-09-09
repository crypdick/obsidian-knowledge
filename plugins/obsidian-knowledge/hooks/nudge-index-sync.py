#!/usr/bin/env python3
"""
Stop hook: nudge the agent to sync parent index.md when this session
created or moved files in wiki/ subfolders without updating the index.

Fires only if:
- Session contains a Write/Edit to wiki/<folder>/<file>.md (file != index.md), OR
  a Bash call with `obsidian move ... to="wiki/..."` or `obsidian rename`
  affecting a wiki path
- The corresponding wiki/<folder>/index.md was NOT itself edited this session
- 5-minute cooldown has elapsed
- stop_hook_active is false
- cwd is inside a configured vault
"""

import json
import os
import re
import sys
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from hookslib.stop_hook import in_cooldown, read_input
from hookslib.transcript import iter_tool_uses
from hookslib.vault_config import is_in_vault

MOVE_RE = re.compile(r'obsidian\s+(?:move|rename)\b[^\n]*?(?:to|name)=["\']?wiki/([^/\s"\']+)/')


def folders_with_new_files(tool_uses: list[dict[str, Any]]) -> set[str]:
    """Return set of wiki folder names where new non-index files were written."""
    folders = set()
    for use in tool_uses:
        name = use.get("name")
        inp = use.get("input", {})
        if name == "Write":
            fp = inp.get("file_path", "")
            m = re.search(r"/wiki/([^/]+)/([^/]+)\.md$", fp)
            if m and m.group(2) != "index":
                folders.add(m.group(1))
        elif name == "Bash":
            cmd = inp.get("command", "")
            for m in MOVE_RE.finditer(cmd):
                folders.add(m.group(1))
    return folders


def folders_with_index_edits(tool_uses: list[dict[str, Any]]) -> set[str]:
    """Return set of wiki folders whose index.md was Written or Edited this session."""
    folders = set()
    for use in tool_uses:
        if use.get("name") not in ("Write", "Edit"):
            continue
        fp = use.get("input", {}).get("file_path", "")
        m = re.search(r"/wiki/([^/]+)/index\.md$", fp)
        if m:
            folders.add(m.group(1))
    return folders


def main() -> None:
    payload = read_input()

    if not is_in_vault(os.getcwd()):
        sys.exit(0)

    transcript_path = payload.get("transcript_path", "")
    if not transcript_path:
        sys.exit(0)

    uses = list(iter_tool_uses(transcript_path))
    new_files = folders_with_new_files(uses)
    index_edits = folders_with_index_edits(uses)
    unsynced = new_files - index_edits

    if not unsynced:
        sys.exit(0)

    if in_cooldown(payload, "nudge-index", cooldown_seconds=300):
        sys.exit(0)

    folders_str = ", ".join(f"wiki/{f}/" for f in sorted(unsynced))
    json.dump(
        {
            "decision": "block",
            "reason": (
                f"Reminder: this session created or moved files under {folders_str} "
                f"without updating the parent index.md. Run vault-organizer, or "
                f"update the index(es) manually."
            ),
        },
        sys.stdout,
    )


if __name__ == "__main__":
    main()
