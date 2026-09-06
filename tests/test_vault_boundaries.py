"""Runtime adapters must agree on vault paths without mutating process state."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from hookslib import vault_config

import hermes_plugin
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
def test_invalid_registry_shapes_are_rejected_consistently(tmp_path, monkeypatch, data):
    registry = tmp_path / "vaults.yaml"
    registry.write_text(json.dumps(data))
    monkeypatch.setattr(vault_config, "CONFIG_PATH", registry)
    assert vault_config.load_vault_roots() == []
    assert load_configured_vaults(registry) == []


@pytest.mark.parametrize("path", ["_sources/original.md", "./_sources/original.md"])
def test_relative_protected_write_is_blocked(tmp_path, monkeypatch, path):
    monkeypatch.setenv("OBSIDIAN_VAULT_ROOT", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    result = hermes_plugin._on_pre_tool_call(
        tool_name="write_file", args={"path": path, "content": "overwrite"}
    )
    assert result and result["action"] == "block"


def test_workdir_checks_are_concurrent_and_never_change_process_cwd(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    outside = tmp_path / "outside"
    vault.mkdir()
    outside.mkdir()
    monkeypatch.setenv("OBSIDIAN_VAULT_ROOT", str(vault))
    original_cwd = os.getcwd()

    def forbid_chdir(path):
        raise AssertionError("protection checks must not change process cwd")

    monkeypatch.setattr(os, "chdir", forbid_chdir)

    def check(workdir):
        return hermes_plugin._on_pre_tool_call(
            tool_name="terminal", args={"command": "rm -r wiki", "workdir": str(workdir)}
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        blocked, allowed = list(pool.map(check, [vault, outside]))
    assert blocked and blocked["action"] == "block"
    assert allowed is None
    assert os.getcwd() == original_cwd


def test_hook_uses_payload_cwd_for_relative_protected_write(subprocess_vault, tmp_path):
    vault, env = subprocess_vault
    hook = Path(__file__).parents[1] / "hooks/protect-vault.py"
    result = subprocess.run(
        [sys.executable, str(hook)],
        input=json.dumps({
            "cwd": str(vault),
            "tool_name": "Write",
            "tool_input": {"file_path": "_sources/original.md", "content": "overwrite"},
        }),
        text=True,
        capture_output=True,
        cwd=tmp_path,
        env=env,
        check=True,
    )
    assert "protected-dir" in result.stdout
