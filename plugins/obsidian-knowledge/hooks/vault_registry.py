"""Dependency-light vault registry shared by standalone hooks and the CLI."""

from __future__ import annotations

import os
from pathlib import Path

import yaml


def load_vault_roots(config_path: Path | None = None) -> list[str]:
    """Read validated YAML roots; missing or empty registries yield no roots."""
    path = config_path or Path(
        os.environ.get(
            "OBSIDIAN_KNOWLEDGE_VAULTS_CONFIG",
            str(Path.home() / ".config" / "obsidian-knowledge" / "vaults.yaml"),
        )
    )
    try:
        data = yaml.safe_load(path.read_text())
    except FileNotFoundError:
        return []
    if data is None:
        return []
    if not isinstance(data, dict):
        raise ValueError(f"vault registry must be a mapping: {path}")
    roots = data.get("vaults")
    if not isinstance(roots, list) or any(not isinstance(root, str) or not root.strip() for root in roots):
        raise ValueError(f"vault registry needs a list of nonempty vault paths: {path}")
    return [str(Path(root).expanduser().resolve()) for root in roots]
