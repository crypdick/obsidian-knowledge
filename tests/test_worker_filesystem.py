"""Real watcher events debounce editor saves without depending on periodic scans."""

import os
import subprocess
import sys
import time

from lib.vault_index.config import VaultIndexConfig
from lib.vault_index.indexer import Indexer, default_cache_dir


def test_real_watcher_embeds_only_settled_revision(tmp_path, monkeypatch, fake_ollama):
    vault = tmp_path / "vault"
    vault.mkdir()
    note = vault / "note.md"
    note.write_text("orchid original")
    monkeypatch.setenv("OBSIDIAN_KNOWLEDGE_CACHE_ROOT", str(tmp_path / "cache"))
    log = tmp_path / "worker.log"

    def hits(query):
        return Indexer(vault, default_cache_dir(vault), VaultIndexConfig(), vector_enabled=False).search(
            query
        )

    def wait_for(query):
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            assert process.poll() is None, log.read_text()
            if hits(query):
                return
            time.sleep(0.05)
        raise AssertionError(f"Worker did not publish {query}: {log.read_text()}")

    with log.open("w") as output:
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "lib.vault_index.cli",
                "index-worker",
                "--vault",
                str(vault),
                "--quiet-seconds",
                "1",
                "--scan-seconds",
                "3600",
            ],
            stdout=output,
            stderr=output,
            env=os.environ.copy(),
        )
        try:
            wait_for("orchid")
            fake_ollama.texts.clear()
            for revision in range(3):
                replacement = vault / "temporary-save"
                replacement.write_text(f"tulip revision {revision}")
                replacement.replace(note)
                time.sleep(0.2)
            assert fake_ollama.texts == []
            assert hits("orchid")
            wait_for("tulip")
            assert fake_ollama.texts == ["tulip revision 2"]
            assert hits("orchid") == []
        finally:
            process.terminate()
            process.wait(timeout=5)
