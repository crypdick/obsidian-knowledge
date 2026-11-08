"""Pydantic models + YAML loader for the vault_index config section."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, FiniteFloat
from vault_preferences import load_preferences


def _valid_regex(value: str) -> str:
    try:
        re.compile(value)
    except re.error as exc:
        raise ValueError(f"invalid path regex: {exc}") from exc
    return value


PathRegex = Annotated[str, AfterValidator(_valid_regex)]


class IndexFilter(BaseModel):
    model_config = ConfigDict(extra="forbid")
    allow_regex: list[PathRegex] = Field(default_factory=list)
    deny_regex: list[PathRegex] = Field(default_factory=list)


class DigestFilter(IndexFilter):
    """Same path grammar as indexing, applied to returned notes."""


class WeightRule(BaseModel):
    model_config = ConfigDict(extra="forbid")
    regex: PathRegex
    multiplier: FiniteFloat


class VaultIndexConfig(BaseModel):
    # NOTE: docs/configuration.md documents search validation at this boundary.
    model_config = ConfigDict(extra="forbid")
    index: IndexFilter = Field(default_factory=IndexFilter)
    digest: DigestFilter = Field(default_factory=DigestFilter)
    weights: list[WeightRule] = Field(default_factory=list)
    default_weight: FiniteFloat = 1.0
    top_k: Annotated[int, Field(strict=True, gt=0)] = 5
    min_score: FiniteFloat | None = None


def load_config(yaml_path: Path | None = None) -> VaultIndexConfig:
    """Load `vault_index:` from the shared, host-independent preferences file.

    Returns defaults if the section is missing. Raises pydantic ValidationError
    if the section is malformed.
    """
    section = load_preferences(yaml_path).root.get("vault_index", {})
    if section is None:
        section = {}
    return VaultIndexConfig.model_validate(section)
