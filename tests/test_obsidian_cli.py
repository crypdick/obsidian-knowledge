"""Native CLI argument isolation, failure mapping, and process cleanup."""

import asyncio
import os
import sys

import pytest

from lib.vault_index import obsidian_cli
from lib.vault_index.obsidian_cli import NativeObsidian


@pytest.fixture
def native(tmp_path, monkeypatch):
    script = tmp_path / "native obsidian"
    script.write_text(
        f"#!{sys.executable}\n"
        + """
import json, os, signal, sys, time
arguments = sys.argv[1:]
command = arguments[1]
if command == "vault":
    print(os.environ["FAKE_NATIVE_VAULT_ROOT"])
elif command == "probe":
    print(json.dumps(arguments))
elif command == "nonzero":
    print("native failed", file=sys.stderr)
    sys.exit(3)
elif command == "emptyerror":
    sys.exit(2)
elif command == "nativeerror":
    print("Error: File not found.")
elif command == "unknownvault":
    print("Vault not found.")
elif command == "noapp":
    print("The CLI is unable to find Obsidian. Please make sure Obsidian is running and try again.")
elif command == "disabled":
    print("Command line interface is not enabled. Please turn it on in Settings > General > Advanced.")
elif command == "properties":
    print("No frontmatter found.")
elif command == "invalidjson":
    print("not json")
elif command == "eval":
    print('=> {"probe":true}')
elif command in ("search", "search:context"):
    print("No matches found.")
elif command == "flood":
    sys.stdout.write("x" * (7 * 1024 * 1024))
elif command == "flooderr":
    sys.stderr.write("x" * (7 * 1024 * 1024))
elif command == "sleep":
    with open(arguments[2], "w") as stream:
        stream.write(str(os.getpid()))
    time.sleep(60)
else:
    print("ordinary output")
"""
    )
    script.chmod(0o755)
    monkeypatch.setenv("OBSIDIAN_KNOWLEDGE_OBSIDIAN_CLI", str(script))
    monkeypatch.setenv("OBSIDIAN_KNOWLEDGE_OBSIDIAN_VAULT", "Fixed Vault")
    monkeypatch.setenv("FAKE_NATIVE_VAULT_ROOT", str(tmp_path))
    return NativeObsidian(tmp_path)


def test_runner_uses_fixed_vault_and_literal_arguments(native, tmp_path):
    injected = "$(touch hacked); `touch hacked`; path with spaces"
    result = asyncio.run(native.run_json("probe", injected))
    assert result == ["vault=Fixed Vault", "probe", injected]
    assert not (tmp_path / "hacked").exists()


@pytest.mark.parametrize(
    ("command", "message"),
    [
        ("nonzero", "native failed"),
        ("emptyerror", "exited with status 2"),
        ("nativeerror", "File not found"),
        ("unknownvault", "vault.*not found"),
        ("noapp", "running"),
        ("disabled", "enabled"),
    ],
)
def test_cli_errors_are_detected_even_on_zero_exit(native, command, message):
    with pytest.raises(ValueError, match=message):
        asyncio.run(native.run(command))


def test_missing_binary_is_actionable(tmp_path, monkeypatch):
    monkeypatch.setenv("OBSIDIAN_KNOWLEDGE_OBSIDIAN_CLI", str(tmp_path / "missing"))
    with pytest.raises(ValueError, match="OBSIDIAN_KNOWLEDGE_OBSIDIAN_CLI"):
        asyncio.run(NativeObsidian(tmp_path).run("version"))


def test_json_normalizes_native_eval_and_empty_search(native):
    assert asyncio.run(native.run_json("eval", "code=JSON.stringify({probe:true})")) == {"probe": True}
    assert asyncio.run(native.run_json("search", "query=none")) == []
    assert asyncio.run(native.run_json("search:context", "query=none")) == []
    assert asyncio.run(native.run_json("properties", "path=empty.md")) == {}
    with pytest.raises(ValueError, match="invalid JSON"):
        asyncio.run(native.run_json("invalidjson"))


@pytest.mark.parametrize("command", ["flood", "flooderr"])
def test_runner_caps_both_output_streams(native, command):
    with pytest.raises(ValueError, match="output exceeds"):
        asyncio.run(native.run(command))


def test_timeout_kills_and_reaps_process(native, tmp_path, monkeypatch):
    monkeypatch.setattr(obsidian_cli, "search_ttl_seconds", lambda: 1)
    marker = tmp_path / "pid"
    with pytest.raises(ValueError, match="timed out"):
        asyncio.run(native.run("sleep", str(marker)))
    with pytest.raises(ProcessLookupError):
        os.kill(int(marker.read_text()), 0)


def test_cancellation_kills_and_reaps_process(native, tmp_path):
    marker = tmp_path / "pid"

    async def exercise():
        task = asyncio.create_task(native.run("sleep", str(marker)))
        for _ in range(200):
            if marker.exists():
                break
            await asyncio.sleep(0.01)
        assert marker.exists()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(exercise())
    with pytest.raises(ProcessLookupError):
        os.kill(int(marker.read_text()), 0)


def test_native_configuration_defaults_and_empty_values(tmp_path, monkeypatch):
    monkeypatch.delenv("OBSIDIAN_KNOWLEDGE_OBSIDIAN_CLI", raising=False)
    monkeypatch.delenv("OBSIDIAN_KNOWLEDGE_OBSIDIAN_VAULT", raising=False)
    instance = NativeObsidian(tmp_path)
    assert instance.binary == "obsidian" and instance.vault_name == tmp_path.name
    monkeypatch.setenv("OBSIDIAN_KNOWLEDGE_OBSIDIAN_CLI", "")
    with pytest.raises(ValueError, match="must not be empty"):
        NativeObsidian(tmp_path)
    path = tmp_path / "not-a-directory"
    path.write_text("file")
    with pytest.raises(ValueError, match="directory"):
        NativeObsidian(path)


@pytest.mark.parametrize("command,arguments", [("", ()), ("probe", ("vault=Other",))])
def test_per_command_vault_override_rejected(native, command, arguments):
    with pytest.raises(ValueError, match="fixed"):
        asyncio.run(native.run(command, *arguments))


def test_wrong_vault_identity_refuses_commands(native, tmp_path, monkeypatch):
    wrong = tmp_path / "other-vault"
    wrong.mkdir()
    monkeypatch.setenv("FAKE_NATIVE_VAULT_ROOT", str(wrong))
    with pytest.raises(ValueError, match="does not match"):
        asyncio.run(native.run("probe"))


def test_unmounted_native_vault_identity_is_actionable(native, tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_NATIVE_VAULT_ROOT", str(tmp_path / "not-mounted"))
    with pytest.raises(ValueError, match="mount the vault"):
        asyncio.run(native.run("probe"))


def test_zero_configured_budget_is_clamped(native, monkeypatch):
    monkeypatch.setattr(obsidian_cli, "search_ttl_seconds", lambda: 0)
    assert asyncio.run(native.run("ordinary")) == "ordinary output\n"
