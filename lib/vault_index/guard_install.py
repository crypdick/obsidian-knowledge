"""Install provider-owned rules and verify the standalone runner dependency."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


def install_rules(base: Path) -> Path:
    """Install missing rules without replacing user edits or disabled rules."""
    if shutil.which("i-insist") is None:
        subprocess.run(["uv", "tool", "install", "git+https://github.com/crypdick/i-insist@main"], check=True)
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
