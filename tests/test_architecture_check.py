"""Exercise architectural import enforcement through its command-line interface."""

import subprocess
import sys
from pathlib import Path

import pytest

CHECK = Path(__file__).resolve().parents[1] / "scripts/prek_hooks/check_architecture.py"


@pytest.mark.parametrize(
    ("filename", "source", "allowed"),
    [
        ("lib/vault_index/indexer.py", "from lib.vault_index.models import Hit", True),
        ("lib/vault_index/indexer.py", "from hookslib.repo_memory import resolve_target", False),
        ("lib/vault_index/primer.py", "from hookslib.repo_memory import resolve_target", True),
        ("lib/vault_index/primer.py", "from hookslib import capture", False),
        ("hooks/hookslib/capture.py", "import lib.vault_index", False),
        ("hooks/hookslib/capture.py", "from . import vault_config", True),
        ("hooks/doctor.py", "from vault_index.indexer import Indexer", True),
        ("hermes_plugin/__init__.py", "from lib import vault_index", False),
        ("hermes_plugin/__init__.py", "import vault_index.indexer", False),
        ("hermes_plugin/__init__.py", "from hookslib import reflect_counter", True),
        ("hermes_plugin/__init__.py", 'command = "import lib.vault_index"', True),
        ("lib/vault_index/indexer.py", "from ...hooks import doctor", False),
        ("lib/vault_index/models.py", "def broken(", False),
    ],
)
def test_import_boundary(tmp_path, filename, source, allowed):
    path = tmp_path / filename
    path.parent.mkdir(parents=True)
    path.write_text(source + "\n")
    result = subprocess.run(
        [sys.executable, str(CHECK), "--root", str(tmp_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert (result.returncode == 0) is allowed, result.stdout + result.stderr
    if not allowed:
        assert f"{filename}:1:" in result.stdout
