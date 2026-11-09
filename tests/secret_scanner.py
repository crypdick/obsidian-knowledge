"""Shared scanner module fixture and isolated Stop-hook driving helpers."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).parent.parent
HOOK_PATH = PLUGIN_ROOT / "hooks" / "scan-vault-secrets.py"


@pytest.fixture(scope="module")
def hook_module():
    """Import scan-vault-secrets.py as a module despite the hyphenated name."""
    sys.path.insert(0, str(PLUGIN_ROOT / "hooks"))
    spec = importlib.util.spec_from_file_location("scan_vault_secrets", HOOK_PATH)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


WEAK = 'password = "synthetic-weak-password"\n'  # pragma: allowlist secret


def configure_vault(hook_module, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(hook_module, "is_in_vault", lambda cwd: True)
    monkeypatch.setattr(hook_module, "matching_vault_root", lambda cwd, roots: str(tmp_path))
    monkeypatch.setattr(hook_module, "load_vault_roots", lambda: [str(tmp_path)])
    monkeypatch.setattr(hook_module, "read_input", dict)
    monkeypatch.setattr(hook_module, "in_cooldown", lambda payload, marker_basename: False)
    emitted: list[str] = []
    monkeypatch.setattr(hook_module, "emit_block", emitted.append)
    return emitted


def run_stop(hook_module):
    try:
        hook_module.main([])
    except SystemExit as stopped:
        assert stopped.code == 0
