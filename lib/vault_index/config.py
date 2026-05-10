"""Pydantic models + YAML loader for the vault_index config section."""
from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field


class IndexFilter(BaseModel):
    allow_regex: list[str] = Field(default_factory=list)
    deny_regex: list[str] = Field(default_factory=list)


class DigestFilter(BaseModel):
    allow_regex: list[str] = Field(default_factory=list)
    deny_regex: list[str] = Field(default_factory=list)


class WeightRule(BaseModel):
    regex: str
    multiplier: float


class VaultIndexConfig(BaseModel):
    index: IndexFilter = Field(default_factory=IndexFilter)
    digest: DigestFilter = Field(default_factory=DigestFilter)
    weights: list[WeightRule] = Field(default_factory=list)
    default_weight: float = 1.0
    top_k: int = 5
    min_score: float | None = None


def load_config(yaml_path: Path) -> VaultIndexConfig:
    """Load `vault_index:` section from `<vault>/.claude/obsidian-knowledge.yaml`.

    Returns defaults if the section is missing. Raises pydantic ValidationError
    if the section is malformed.
    """
    if not yaml_path.exists():
        return VaultIndexConfig()
    raw = yaml.safe_load(yaml_path.read_text()) or {}
    section = raw.get("vault_index", {}) or {}
    return VaultIndexConfig.model_validate(section)
