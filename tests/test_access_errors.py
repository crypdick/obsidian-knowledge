"""Distinguish sandbox restrictions from service and storage failures."""

from __future__ import annotations

import argparse
import errno
import io
import urllib.error
from unittest.mock import Mock

import pytest

from hooks.doctor import check_ollama
from lib.vault_index.cli import run_papercut
from lib.vault_index.config import VaultIndexConfig
from lib.vault_index.indexer import Indexer


@pytest.fixture(autouse=True)
def _disable_ollama_probe():
    """Exercise the real probe here; each test stubs its HTTP boundary."""


@pytest.mark.parametrize("error_number", [errno.EPERM, errno.EACCES, errno.ECONNREFUSED])
@pytest.mark.parametrize("wrapped", [False, True])
def test_search_and_doctor_distinguish_network_denial(tmp_path, monkeypatch, error_number, wrapped):
    error = OSError(error_number, "network failure")
    failure = urllib.error.URLError(error) if wrapped else error
    request = Mock(side_effect=failure)
    monkeypatch.setattr("urllib.request.urlopen", request)
    monkeypatch.delenv("OBSIDIAN_KNOWLEDGE_SKIP_OLLAMA_PROBE", raising=False)
    idx = Indexer(tmp_path, tmp_path / "cache", VaultIndexConfig())

    assert not idx.vector_enabled
    warning = check_ollama(str(tmp_path))
    assert warning is not None
    for message in (idx.vector_status, warning):
        if error_number == errno.ECONNREFUSED:
            assert "Ollama unreachable" in message
            assert "access denied" not in message
        else:
            assert "Ollama access denied" in message
            assert "approved network access" in message
            assert "Ollama unreachable" not in message
        assert "ollama serve" not in message
        assert "ollama pull" not in message


def test_missing_model_has_model_specific_recovery(tmp_path, monkeypatch):
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **kw: io.BytesIO(b'{"models": []}'))
    monkeypatch.setenv("MEMWEAVE_EMBEDDING_MODEL", "ollama/bge-m3")
    idx = Indexer(tmp_path, tmp_path / "cache", VaultIndexConfig())

    assert not idx.vector_enabled
    assert "ollama pull bge-m3" in idx.vector_status
    assert "access denied" not in idx.vector_status


@pytest.mark.parametrize("error_number", [errno.EROFS, errno.EACCES, errno.EPERM, errno.ENOSPC])
def test_papercut_write_failure_is_not_a_usage_error(tmp_path, monkeypatch, capsys, error_number):
    record = Mock(side_effect=OSError(error_number, "write failed", str(tmp_path / ".PAPERCUTS.md.lock")))
    monkeypatch.setattr("lib.vault_index.papercuts.record_papercut", record)

    result = run_papercut(vault=tmp_path, description="original friction", parser=argparse.ArgumentParser())

    output = capsys.readouterr()
    assert result == 1
    assert output.out == ""
    assert "could not complete vault log write" in output.err
    assert "usage:" not in output.err
    assert str(tmp_path) in output.err
    record.assert_called_once_with(tmp_path, "original friction")
    if error_number == errno.ENOSPC:
        assert "approved permission" not in output.err
    else:
        assert "approved permission mechanism" in output.err
        assert "do not recursively log" in output.err
