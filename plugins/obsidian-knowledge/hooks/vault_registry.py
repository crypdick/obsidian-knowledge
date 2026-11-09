"""Dependency-light vault registry shared by standalone hooks and the CLI."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml


def registry_path() -> Path:
    """Resolve host-local registry path; never store paths in portable preferences."""
    return Path(
        os.environ.get(
            "OBSIDIAN_KNOWLEDGE_VAULTS_CONFIG",
            str(
                Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))
                / "obsidian-knowledge/vaults.yaml"
            ),
        )
    )


def read_registry(path: Path) -> dict[str, Any]:
    """Validate the registry mapping, preserving unrelated host adapter settings."""
    try:
        data = yaml.safe_load(path.read_text())
    except FileNotFoundError:
        return {}
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ValueError(f"expected a YAML mapping in {path}")
    roots = data.get("vaults", [])
    if not isinstance(roots, list) or any(not isinstance(root, str) or not root.strip() for root in roots):
        raise ValueError(f"expected a list of nonempty paths under 'vaults' in {path}")
    return data


def load_vault_roots(config_path: Path | None = None) -> list[str]:
    """Read normalized roots; missing, empty and partial registries yield no roots."""
    data = read_registry(config_path or registry_path())
    return [str(Path(root).expanduser().resolve()) for root in data.get("vaults", [])]
