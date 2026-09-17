"""Runtime adapters must agree on vault paths without mutating process state."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from hookslib import vault_config

from lib.vault_index.cli import load_configured_vaults


@pytest.mark.parametrize("entry", ['"{vault}" # primary vault', "'{vault}'", "{vault}"])
def test_registry_parsing_agrees_across_adapters(tmp_path, monkeypatch, entry):
    vault = tmp_path / "vault"
    registry = tmp_path / "vaults.yaml"
    registry.write_text("vaults:\n  - " + entry.format(vault=vault) + "\n")
    monkeypatch.setattr(vault_config, "CONFIG_PATH", registry)
    assert vault_config.load_vault_roots() == [str(vault)]
    assert load_configured_vaults(registry) == [vault]


def test_registry_override_agrees_across_adapters(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    registry = tmp_path / "vaults.yaml"
    registry.write_text(json.dumps({"vaults": [str(vault)]}))
    monkeypatch.setenv("OBSIDIAN_KNOWLEDGE_VAULTS_CONFIG", str(registry))
    assert vault_config.load_vault_roots() == [str(vault)]
    assert load_configured_vaults() == [vault]


@pytest.mark.parametrize("data", [None, [], "vault", {"vaults": "vault"}, {"vaults": [None]}])
def test_hooks_ignore_invalid_registry_but_cli_reports_it(tmp_path, monkeypatch, data):
    registry = tmp_path / "vaults.yaml"
    registry.write_text(json.dumps(data))
    monkeypatch.setattr(vault_config, "CONFIG_PATH", registry)
    assert vault_config.load_vault_roots() == []
    if data is None:
        assert load_configured_vaults(registry) == []
    else:
        with pytest.raises(ValueError):
            load_configured_vaults(registry)


def test_hook_uses_payload_cwd_for_relative_protected_write(subprocess_vault, tmp_path):
    vault, env = subprocess_vault
    hook = Path(__file__).parents[1] / "hooks/protect-vault.py"
    result = subprocess.run(
        [sys.executable, str(hook)],
        input=json.dumps(
            {
                "cwd": str(vault),
                "tool_name": "Write",
                "tool_input": {"file_path": "_sources/original.md", "content": "overwrite"},
            }
        ),
        text=True,
        capture_output=True,
        cwd=tmp_path,
        env=env,
        check=True,
    )
    assert "protected-dir" in result.stdout
