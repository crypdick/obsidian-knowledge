"""The CLI process always exits, even when its output reader is gone."""

from __future__ import annotations

import os
import subprocess
import sys

from lib.vault_index.index_worker import foreground_reindex


def test_search_exits_when_stdout_reader_is_gone(tmp_path, monkeypatch, fake_ollama):
    monkeypatch.setenv("OBSIDIAN_KNOWLEDGE_CACHE_ROOT", str(tmp_path / "cache"))
    (tmp_path / "wiki").mkdir()
    (tmp_path / "wiki/orchid.md").write_text("# Orchid\n\nPurple greenhouse orchids\n")
    foreground_reindex(tmp_path)

    # A killed parent leaves the pipe without a reader; flushing then raises
    # BrokenPipeError. That must not skip the hard exit and wait on threads.
    reader, writer = os.pipe()
    os.close(reader)
    process = subprocess.Popen(
        [sys.executable, "-m", "lib.vault_index.cli", "search", "orchid", "--vault", str(tmp_path)],
        stdout=writer,
        stderr=subprocess.DEVNULL,
    )
    os.close(writer)
    try:
        process.wait(timeout=15)
    finally:
        process.kill()
    assert process.returncode is not None


def test_base_exceptions_still_exit_hard(monkeypatch):
    from lib.vault_index import cli

    exits: list[int] = []
    monkeypatch.setattr(cli.os, "_exit", exits.append)
    for raised, code in [
        (SystemExit(2), 2),
        (SystemExit(None), 0),
        (SystemExit("usage"), 1),
        (KeyboardInterrupt(), 130),
    ]:
        monkeypatch.setattr(cli, "main", lambda raised=raised: (_ for _ in ()).throw(raised))
        cli.cli_main()
        assert exits[-1] == code


def test_unwritable_streams_still_exit_hard(monkeypatch):
    from lib.vault_index import cli

    class Broken:
        def flush(self):
            raise BrokenPipeError

    exits: list[int] = []
    monkeypatch.setattr(cli.os, "_exit", exits.append)
    monkeypatch.setattr(cli.sys, "stdout", Broken())
    cli._exit_hard(0)
    assert exits == [0]


def test_deadline_kills_work_that_holds_the_gil(tmp_path):
    """Neither SIGALRM nor a watchdog thread can run while C code holds the GIL."""
    import time

    script = (
        "import ctypes, signal\n"
        "from lib.vault_index.cli import search_ttl\n"
        "signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGALRM})\n"
        "with search_ttl(1, label='reindex'):\n"
        "    ctypes.PyDLL(None).sleep(60)\n"  # a C call that keeps holding the GIL
    )
    started = time.monotonic()
    process = subprocess.Popen([sys.executable, "-c", script], stderr=subprocess.PIPE, text=True)
    try:
        _, stderr = process.communicate(timeout=20)
    finally:
        process.kill()
    assert process.returncode == -9
    assert time.monotonic() - started < 18
    assert "reindex: killed" in stderr
