"""A configured writer owns CLI mutations, including failures and stdin."""

import json
import os
import subprocess
import sys

import pytest
import yaml

from lib.vault_index import cli


@pytest.mark.parametrize("command", ["write", "papercut", "garden"])
@pytest.mark.parametrize("repository", ["", "acme/tools"])
@pytest.mark.parametrize("explicit_vault", [True, False])
def test_configured_writer_receives_original_call(tmp_path, monkeypatch, command, repository, explicit_vault):
    if repository:
        subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
        subprocess.run(
            ["git", "-C", str(tmp_path), "remote", "add", "origin", f"https://example.com/{repository}.git"],
            check=True,
        )
    receipt = tmp_path / "receipt.json"
    writer = tmp_path / "writer.py"
    writer.write_text(
        "import json,os,sys\n"
        "from pathlib import Path\n"
        "Path(sys.argv[1]).write_text(json.dumps([sys.argv[2:],sys.stdin.read(),os.getcwd()]))\n"
        "sys.exit(7)\n"
    )
    registry = tmp_path / "vaults.yaml"
    registry.write_text(
        yaml.safe_dump(
            {
                "vaults": [str(tmp_path)],
                "write_command": [sys.executable, str(writer), str(receipt)],
            }
        )
    )
    monkeypatch.setenv("OBSIDIAN_KNOWLEDGE_VAULTS_CONFIG", str(registry))
    monkeypatch.chdir(tmp_path)
    arguments = [command, "audit" if command == "garden" else "note.md"]
    if explicit_vault:
        arguments += ["--vault", str(tmp_path)]
    monkeypatch.setattr(sys, "argv", ["obsidian-knowledge", *arguments])
    with (tmp_path / "input.txt").open("w+") as stream:
        stream.write("literal $text\\n\n")
        stream.seek(0)
        monkeypatch.setattr(sys, "stdin", stream)
        assert cli.main() == 7
    if not explicit_vault:
        arguments += ["--vault", str(tmp_path)]
    if command == "papercut":
        arguments += ["--repository", repository]
    assert json.loads(receipt.read_text()) == [arguments, "literal $text\\n\n", str(tmp_path)]
    assert not (tmp_path / "note.md").exists()
    assert not (tmp_path / "wiki").exists()


@pytest.mark.parametrize("invalid", [[], "sudo", [1], [""]])
def test_invalid_writer_rejected_before_local_write(tmp_path, monkeypatch, invalid):
    registry = tmp_path / "vaults.yaml"
    registry.write_text(yaml.safe_dump({"vaults": [str(tmp_path)], "write_command": invalid}))
    monkeypatch.setenv("OBSIDIAN_KNOWLEDGE_VAULTS_CONFIG", str(registry))
    monkeypatch.setattr(sys, "argv", ["obsidian-knowledge", "write", "note.md"])
    with pytest.raises(ValueError, match="write_command"):
        cli.main()
    assert not (tmp_path / "note.md").exists()


def test_explicit_unregistered_vault_keeps_local_write_behavior(tmp_path, monkeypatch):
    registered, local = tmp_path / "shared", tmp_path / "local"
    registered.mkdir()
    local.mkdir()
    registry = tmp_path / "vaults.yaml"
    registry.write_text(
        yaml.safe_dump(
            {
                "vaults": [str(registered)],
                "write_command": [str(tmp_path / "must-not-run")],
            }
        )
    )
    monkeypatch.setenv("OBSIDIAN_KNOWLEDGE_VAULTS_CONFIG", str(registry))
    monkeypatch.setattr(sys, "argv", ["obsidian-knowledge", "write", "note.md", "--vault", str(local)])
    with (tmp_path / "input.txt").open("w+") as stream:
        stream.write("# Local note\n")
        stream.seek(0)
        monkeypatch.setattr(sys, "stdin", stream)
        assert cli.main() == 0
    assert (local / "note.md").read_text() == "# Local note\n"
    assert (local / "note.md").stat().st_uid == os.geteuid()
    assert not (registered / "note.md").exists()
