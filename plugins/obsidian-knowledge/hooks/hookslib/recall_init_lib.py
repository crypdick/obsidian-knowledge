"""Helpers for the SessionStart recall-init hook.

Re-exports build_primer from the shared lib so CC and Hermes adapters
use a single source.

Import strategy: the CC hook runner inserts hooks/ onto sys.path before
importing this module, which means 'lib' in sys.modules already resolves
to hooks/lib (not the project root's lib package). To import from the
project-root lib without a name collision, we locate the shared module by
absolute path via importlib and extract build_primer from it directly.
This avoids mutating sys.modules or relying on import-order assumptions.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

# Project root: three levels up from this file (hooks/lib/recall_init_lib.py)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_PRIMER_PATH = _PROJECT_ROOT / "lib" / "vault_index" / "primer.py"

if "vault_index.primer" in sys.modules:
    _primer_mod = sys.modules["vault_index.primer"]
else:
    _spec = importlib.util.spec_from_file_location("vault_index.primer", _PRIMER_PATH)
    assert _spec and _spec.loader, f"Cannot load primer from {_PRIMER_PATH}"
    _primer_mod = importlib.util.module_from_spec(_spec)
    sys.modules["vault_index.primer"] = _primer_mod
    _spec.loader.exec_module(_primer_mod)  # type: ignore[union-attr]

build_primer = _primer_mod.build_primer

__all__ = ["build_primer"]
