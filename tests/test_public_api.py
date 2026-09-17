"""Tests for package-level lazy exports."""

import pytest

import lib.vault_index as vault_index


def test_indexer_is_available_from_public_package():
    from lib.vault_index.indexer import Indexer

    assert vault_index.Indexer is Indexer


def test_unknown_public_attribute_raises_clear_error():
    with pytest.raises(AttributeError, match="has no attribute 'unknown'"):
        getattr(vault_index, "unknown")  # noqa: B009 - dynamic fallback is behavior under test
