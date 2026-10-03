"""Configured vault defaults for standalone gardener scripts."""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "hooks"))
from vault_registry import load_vault_roots


def resolve_vault(explicit: Path | None = None) -> Path:
    """Use an explicit root, the enclosing configured vault, or the sole vault."""
    try:
        if explicit is None:
            roots = tuple(Path(root) for root in load_vault_roots())
            cwd = Path.cwd().resolve()
            explicit = next((root for root in roots if cwd.is_relative_to(root)), None)
            if explicit is None:
                if len(roots) != 1:
                    raise ValueError("pass a vault path when no single configured vault applies")
                explicit = roots[0]
        root = explicit.expanduser().resolve(strict=True)
        if not root.is_dir():
            raise ValueError(f"not a vault directory: {root}")
        return root
    except (OSError, ValueError, yaml.YAMLError) as exc:
        raise SystemExit(f"Error: {exc}") from exc
