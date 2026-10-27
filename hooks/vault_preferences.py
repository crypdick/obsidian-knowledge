"""Host-independent preferences shared by the CLI, hooks, and maintenance tools."""

from __future__ import annotations

import os
from pathlib import Path

import yaml
from pydantic import JsonValue, RootModel, field_validator, model_validator


class Preferences(RootModel[dict[str, JsonValue]]):
    """Parse shared settings without accepting the host's vault registry."""

    @field_validator("root", mode="before")
    @classmethod
    def mapping_document(cls, value: object) -> object:
        if not isinstance(value, dict):
            raise ValueError("expected a YAML mapping in shared preferences")
        return value

    @model_validator(mode="after")
    def exclude_vault_locations(self) -> Preferences:
        if "vaults" in self.root:
            raise ValueError("vault locations belong in the host-local vaults.yaml, not shared preferences")
        return self


def preferences_path() -> Path:
    """Locate shared preferences independently of host-local vault registration."""
    override = os.environ.get("OBSIDIAN_KNOWLEDGE_CONFIG")
    if override:
        return Path(override).expanduser()
    base = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))).expanduser()
    return base / "obsidian-knowledge/config.yaml"


def load_preferences(path: Path | None = None) -> Preferences:
    """Load one shared preferences file; missing or empty files use defaults."""
    selected = path if path is not None else preferences_path()
    try:
        raw = yaml.safe_load(selected.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raw = None
    return Preferences.model_validate({} if raw is None else raw)
