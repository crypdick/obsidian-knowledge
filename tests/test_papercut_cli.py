"""End-to-end CLI tests for repository-scoped papercut logs."""

import os
import subprocess
import sys
from pathlib import Path


def test_cli_papercut_records_an_entry_without_loading_the_search_index(tmp_path: Path):
    vault = tmp_path / "vault"
    knowledge_base = vault / "wiki" / "systems" / "knowledge-base"
    knowledge_base.mkdir(parents=True)
    (knowledge_base / "index.md").write_text("# Knowledge Base\n")
    workdir = tmp_path / "work"
    subprocess.run(["git", "init", "-q", str(workdir)], check=True)
    subprocess.run(
        ["git", "-C", str(workdir), "remote", "add", "origin", "git@github.com:acme/agent-tools.git"],
        check=True,
    )
    source_root = Path(__file__).parents[1]
    pythonpath = str(source_root)
    if existing_pythonpath := os.environ.get("PYTHONPATH"):
        pythonpath = f"{pythonpath}{os.pathsep}{existing_pythonpath}"

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "lib.vault_index.cli",
            "papercut",
            "the command did not explain the failure",
            "--vault",
            str(vault),
        ],
        cwd=workdir,
        capture_output=True,
        env={**os.environ, "PYTHONPATH": pythonpath},
        text=True,
    )

    assert result.returncode == 0, result.stderr
    expected = vault / "wiki" / "repos" / "acme" / "agent-tools" / "PAPERCUTS.md"
    assert "Logged papercut: wiki/repos/acme/agent-tools/PAPERCUTS.md" in result.stdout
    assert "the command did not explain the failure" in expected.read_text()


def test_cli_papercut_keeps_concurrent_process_entries_intact(tmp_path: Path):
    vault = tmp_path / "vault"
    vault.mkdir()
    workdir = tmp_path / "work"
    workdir.mkdir()
    source_root = Path(__file__).parents[1]
    pythonpath = str(source_root)
    if existing_pythonpath := os.environ.get("PYTHONPATH"):
        pythonpath = f"{pythonpath}{os.pathsep}{existing_pythonpath}"
    env = {**os.environ, "PYTHONPATH": pythonpath}

    descriptions = [f"concurrent CLI papercut {number}" for number in range(4)]
    processes = [
        subprocess.Popen(
            [sys.executable, "-m", "lib.vault_index.cli", "papercut", description, "--vault", str(vault)],
            cwd=workdir,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for description in descriptions
    ]

    for process in processes:
        stdout, stderr = process.communicate(timeout=10)
        assert process.returncode == 0, f"{stdout}\n{stderr}"

    log = vault / "wiki" / "systems" / "knowledge-base" / "PAPERCUTS.md"
    text = log.read_text()
    assert text.count("## ") == len(descriptions)
    for description in descriptions:
        assert description in text
