"""Pydantic models + YAML loader for the vault_index config section."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field
from vault_preferences import load_preferences


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


def load_config(yaml_path: Path | None = None) -> VaultIndexConfig:
    """Load `vault_index:` from the shared, host-independent preferences file.

    Returns defaults if the section is missing. Raises pydantic ValidationError
    if the section is malformed.
    """
    section = load_preferences(yaml_path).root.get("vault_index", {})
    if section is None:
        section = {}
    return VaultIndexConfig.model_validate(section)
