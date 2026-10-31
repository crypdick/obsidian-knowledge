"""Exercise installed CLI as one end-to-end public seam."""

from pathlib import Path

import pytest

from scripts.cli_smoke_test import exercise


@pytest.mark.timeout(120)
def test_installed_cli(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Keep automated installation checks independent of host Ollama load.
    # The standalone smoke command still exercises the live embedding service.
    monkeypatch.setenv("MEMWEAVE_EMBEDDING_API_BASE", "http://127.0.0.1:1")
    executable = Path(__file__).parents[1] / ".venv" / "bin" / "obsidian-knowledge"
    exercise(str(executable), tmp_path)
