"""Hermes plugin entrypoint for obsidian-knowledge.

Installed with:

    hermes plugins install crypdick/obsidian-knowledge --enable

The same checkout exposes:
- lifecycle hooks via the normal Hermes plugin manager
- the obsidian-knowledge MemoryProvider via Hermes's memory provider loader
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any


PLUGIN_ROOT = Path(__file__).resolve().parent
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))


def register(ctx: Any) -> None:
    from hermes_plugin import ObsidianKnowledgeProvider  # noqa: WPS433
    from hermes_plugin import register as register_hooks  # noqa: WPS433

    register_hooks(ctx)

    register_memory_provider = getattr(ctx, "register_memory_provider", None)
    if callable(register_memory_provider):
        register_memory_provider(ObsidianKnowledgeProvider())
