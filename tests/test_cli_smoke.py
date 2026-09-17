"""Exercise installed CLI as one end-to-end public seam."""

from pathlib import Path

import pytest

from scripts.cli_smoke_test import exercise


@pytest.mark.timeout(60)
def test_installed_cli(tmp_path: Path) -> None:
    executable = Path(__file__).parents[1] / ".venv" / "bin" / "obsidian-knowledge"
    exercise(str(executable), tmp_path)
