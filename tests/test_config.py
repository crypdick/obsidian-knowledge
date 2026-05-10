"""Tests for vault_index config loading."""
import textwrap
from pathlib import Path

import pytest

from lib.vault_index.config import (
    IndexFilter,
    DigestFilter,
    WeightRule,
    VaultIndexConfig,
    load_config,
)


def test_vault_index_config_defaults():
    cfg = VaultIndexConfig()
    assert cfg.index.allow_regex == []
    assert cfg.index.deny_regex == []
    assert cfg.digest.allow_regex == []
    assert cfg.digest.deny_regex == []
    assert cfg.weights == []
    assert cfg.default_weight == 1.0
    assert cfg.top_k == 5
    assert cfg.min_score is None


def test_vault_index_config_from_dict():
    cfg = VaultIndexConfig.model_validate({
        "index": {"deny_regex": ["^Journal/"]},
        "digest": {"allow_regex": ["^wiki/"]},
        "weights": [{"regex": "^wiki/", "multiplier": 1.5}],
        "default_weight": 1.0,
        "top_k": 10,
    })
    assert cfg.index.deny_regex == ["^Journal/"]
    assert cfg.digest.allow_regex == ["^wiki/"]
    assert len(cfg.weights) == 1
    assert cfg.weights[0].regex == "^wiki/"
    assert cfg.weights[0].multiplier == 1.5
    assert cfg.top_k == 10


def test_load_config_from_yaml(tmp_path: Path):
    yaml_path = tmp_path / "obsidian-knowledge.yaml"
    yaml_path.write_text(textwrap.dedent("""
        vault_index:
          index:
            deny_regex: ["^Journal/"]
          digest:
            allow_regex: ["^wiki/"]
          weights:
            - regex: "^wiki/"
              multiplier: 1.5
          top_k: 10
    """))
    cfg = load_config(yaml_path)
    assert cfg.index.deny_regex == ["^Journal/"]
    assert cfg.weights[0].multiplier == 1.5
    assert cfg.top_k == 10


def test_load_config_missing_section_returns_defaults(tmp_path: Path):
    yaml_path = tmp_path / "obsidian-knowledge.yaml"
    yaml_path.write_text("ai_managed:\n  - wiki\n")
    cfg = load_config(yaml_path)
    assert cfg.top_k == 5  # default
