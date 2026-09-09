"""Validate and atomically update the CLI's vault registry."""

from __future__ import annotations

import fcntl
import os
import tempfile
from pathlib import Path
from typing import Any

import yaml


def existing_vault(path: Path) -> Path:
    if not path.expanduser().exists():
        raise ValueError(f"vault does not exist or is not a directory: {path}")
    root = path.expanduser().resolve(strict=True)
    if not root.is_dir():
        raise ValueError(f"vault is not a directory: {root}")
    return root


def read_registry(registry: Path) -> dict[str, Any]:
    data = yaml.safe_load(registry.read_text()) if registry.exists() else None
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise ValueError(f"expected a YAML mapping in {registry}")
    roots = data.get("vaults", [])
    if not isinstance(roots, list) or any(not isinstance(p, str) or not p.strip() for p in roots):
        raise ValueError(f"expected a list of nonempty paths under 'vaults' in {registry}")
    return data


def register_vault(vault: Path, registry: Path) -> bool:
    """Register an existing vault; return False when already registered.

    Validate existing YAML before touching it, preserve other keys, and compare
    normalized paths rather than substrings. Lock across read/modify/replace.
    """
    vault = existing_vault(vault)
    registry.parent.mkdir(parents=True, exist_ok=True)
    with registry.with_suffix(registry.suffix + ".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        data = read_registry(registry)
        roots = data.get("vaults", [])
        if vault in [Path(p).expanduser().resolve() for p in roots]:
            return False
        data["vaults"] = [*roots, str(vault)]
        fd, name = tempfile.mkstemp(prefix=f".{registry.name}.", dir=registry.parent)
        temporary = Path(name)
        try:
            with os.fdopen(fd, "w") as stream:
                yaml.safe_dump(data, stream, sort_keys=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, registry)
        finally:
            temporary.unlink(missing_ok=True)
    return True
