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


def test_checker_uses_event_paths_from_another_cwd(subprocess_vault, tmp_path):
    vault, env = subprocess_vault
    result = subprocess.run(
        [sys.executable, str(Path(__file__).parents[1] / "hooks/i_insist.py"), "protected-dirs"],
        input=json.dumps(
            {
                "cwd": str(vault),
                "kind": "file_write",
                "paths": [str(vault / "_sources/original.md")],
                "changes": [
                    {
                        "path": str(vault / "_sources/original.md"),
                        "operation": "write",
                        "content": "overwrite",
                    }
                ],
            }
        ),
        text=True,
        capture_output=True,
        cwd=tmp_path,
        env=env,
        check=True,
    )
    assert json.loads(result.stdout) is True
