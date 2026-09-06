"""Dependency-light vault registry shared by standalone hooks and the CLI."""

from __future__ import annotations

import os
from pathlib import Path

import yaml


def load_vault_roots(config_path: Path | None = None) -> list[str]:
    """Read validated YAML roots; missing or invalid registries yield no roots."""
    path = config_path or Path(
        os.environ.get(
            "OBSIDIAN_KNOWLEDGE_VAULTS_CONFIG",
            str(Path.home() / ".config" / "obsidian-knowledge" / "vaults.yaml"),
        )
    )
    try:
        data = yaml.safe_load(path.read_text())
    except (OSError, yaml.YAMLError):
        return []
    if not isinstance(data, dict):
        return []
    roots = data.get("vaults")
    if not isinstance(roots, list) or any(not isinstance(root, str) or not root.strip() for root in roots):
        return []
    return [str(Path(root).expanduser().resolve()) for root in roots]
