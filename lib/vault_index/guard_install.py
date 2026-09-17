"""Install provider-owned rules and verify the standalone runner dependency."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path


def install_rules(base: Path) -> Path:
    """Install missing rules without replacing user edits or disabled rules."""
    current = None
    if shutil.which("i-insist"):
        result = subprocess.run(["i-insist", "--version"], capture_output=True, text=True, check=False)
        current = (
            re.fullmatch(r"i-insist (\d+)\.(\d+)\.(\d+)", result.stdout.strip())
            if result.returncode == 0
            else None
        )
    # NOTE: docs/hooks.md records the minimum version for neutral file changes.
    if current is None or tuple(map(int, current.groups())) < (0, 3, 0):
        subprocess.run(["uv", "tool", "install", "--upgrade", "i-insist>=0.3.0"], check=True)
    subprocess.run(["i-insist", "ensure"], check=True)
    source = Path(__file__).resolve().parents[2] / "hooks" / "i-insist.toml"
    text = source.read_text()
    destination = base / ".i-insist" / "obsidian-knowledge.toml"
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        with destination.open("x") as stream:
            stream.write(text)
    except FileExistsError:
        pass
    return destination
