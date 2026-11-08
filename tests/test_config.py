"""Tests for vault_index config loading."""

import textwrap
from pathlib import Path

import pytest
from pydantic import ValidationError

from lib.vault_index.config import (
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
    cfg = VaultIndexConfig.model_validate(
        {
            "index": {"deny_regex": ["^Journal/"]},
            "digest": {"allow_regex": ["^wiki/"]},
            "weights": [{"regex": "^wiki/", "multiplier": 1.5}],
            "default_weight": 1.0,
            "top_k": 10,
        }
    )
    assert cfg.index.deny_regex == ["^Journal/"]
    assert cfg.digest.allow_regex == ["^wiki/"]
    assert len(cfg.weights) == 1
    assert cfg.weights[0].regex == "^wiki/"
    assert cfg.weights[0].multiplier == 1.5
    assert cfg.top_k == 10


def test_load_config_from_yaml(tmp_path: Path):
    yaml_path = tmp_path / "obsidian-knowledge.yaml"
    yaml_path.write_text(
        textwrap.dedent("""
        vault_index:
          index:
            deny_regex: ["^Journal/"]
          digest:
            allow_regex: ["^wiki/"]
          weights:
            - regex: "^wiki/"
              multiplier: 1.5
          top_k: 10
    """)
    )
    cfg = load_config(yaml_path)
    assert cfg.index.deny_regex == ["^Journal/"]
    assert cfg.weights[0].multiplier == 1.5
    assert cfg.top_k == 10


def test_load_config_missing_section_returns_defaults(tmp_path: Path):
    yaml_path = tmp_path / "obsidian-knowledge.yaml"
    yaml_path.write_text("ai_managed:\n  - wiki\n")
    cfg = load_config(yaml_path)
    assert cfg.top_k == 5  # default


def test_load_config_missing_file_returns_defaults(tmp_path: Path):
    assert load_config(tmp_path / "missing.yaml") == VaultIndexConfig()


def test_load_config_empty_file_returns_defaults(tmp_path: Path):
    yaml_path = tmp_path / "obsidian-knowledge.yaml"
    yaml_path.write_text("")
    assert load_config(yaml_path) == VaultIndexConfig()


def test_load_config_null_section_returns_defaults(tmp_path: Path):
    yaml_path = tmp_path / "obsidian-knowledge.yaml"
    yaml_path.write_text("vault_index: null\n")
    assert load_config(yaml_path) == VaultIndexConfig()


def test_load_config_rejects_non_mapping_document(tmp_path: Path):
    yaml_path = tmp_path / "obsidian-knowledge.yaml"
    yaml_path.write_text("- not\n- a mapping\n")
    with pytest.raises(ValueError, match="expected a YAML mapping"):
        load_config(yaml_path)


@pytest.mark.parametrize(
    "section",
    [{"top_k": value} for value in (0, -1, True, 1.5, "5")]
    + [
        {"topk": 1},
        {"index": {"deny_regex": ["["]}},
        {"digest": {"allow_regex": ["("]}},
        {"weights": [{"regex": "[", "multiplier": 1}]},
        {"index": {"deny_regez": []}},
        {"weights": [{"regex": ".*", "multiplier": float("nan")}]},
        {"default_weight": float("inf")},
        {"min_score": float("-inf")},
    ],
)
def test_load_config_rejects_invalid_search_semantics(tmp_path, section):
    import yaml

    path = tmp_path / "preferences.yaml"
    path.write_text(yaml.safe_dump({"vault_index": section}))
    with pytest.raises(ValidationError):
        load_config(path)


def test_search_validation_keeps_negative_finite_weights():
    cfg = VaultIndexConfig(weights=[{"regex": "^wiki/", "multiplier": -1}], default_weight=0)
    assert cfg.weights[0].multiplier == -1
    assert cfg.default_weight == 0
