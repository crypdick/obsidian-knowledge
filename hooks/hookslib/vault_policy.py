"""Per-vault policy loader.

Reads `<vault>/.claude/obsidian-knowledge.yaml` — a single config file
that describes vault-specific policy (publishable zones, dg-publish
allowlist, generic-filename block list, illegal-character set, zone
descriptors). New in plugin v2.0; replaces the older split layout
(`vault-zones.yaml` + `publish-rules.yaml` + inline lists in
vault-local hooks).

Each section is optional. A missing section means the corresponding
rule no-ops, so users without these concerns pay no enforcement cost
and don't need to write any config.
"""
from __future__ import annotations

import os
from typing import Any

try:
    import yaml  # type: ignore[import-not-found]

    _HAVE_YAML = True
except ImportError:  # pragma: no cover — PyYAML optional but expected
    _HAVE_YAML = False


CONFIG_BASENAME = ".claude/obsidian-knowledge.yaml"

_cache: dict[str, dict[str, Any]] = {}


def load_vault_policy(vault_root: str) -> dict[str, Any]:
    """Load and cache the per-vault policy config. Returns {} if absent."""
    if not _HAVE_YAML:
        return {}
    if vault_root in _cache:
        return _cache[vault_root]
    config_path = os.path.join(vault_root, CONFIG_BASENAME)
    if not os.path.isfile(config_path):
        _cache[vault_root] = {}
        return _cache[vault_root]
    try:
        with open(config_path) as f:
            data = yaml.safe_load(f) or {}
    except (OSError, yaml.YAMLError):
        data = {}
    _cache[vault_root] = data
    return data


def find_containing_vault(file_path: str, vault_roots: list[str]) -> str | None:
    """Return the vault root that contains `file_path`, or None."""
    abs_path = os.path.abspath(os.path.expanduser(file_path))
    for root in vault_roots:
        if abs_path == root or abs_path.startswith(root + os.sep):
            return root
    return None
