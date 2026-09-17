"""Subprocess tests for hooks/doctor.py."""

import io
import json
import os
import runpy
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

HOOK = Path(__file__).parent.parent / "hooks" / "doctor.py"

# Unique per-process so the session-keyed debounce marker never collides
# with a prior test run.
RUN_ID = f"{os.getpid()}-{uuid.uuid4().hex[:8]}"


def run_hook(cwd: str, env: dict | None = None, payload: dict | None = None) -> str:
    proc = subprocess.run(
        ["python3", str(HOOK)],
        input=json.dumps(payload or {}),
        capture_output=True,
        text=True,
        cwd=cwd,
        env=env,
    )
    return proc.stdout


def run_raw_hook(cwd: str, payload: str, env: dict | None = None) -> str:
    proc = subprocess.run(
        ["python3", str(HOOK)],
        input=payload,
        capture_output=True,
        text=True,
        cwd=cwd,
        env=env,
    )
    return proc.stdout


@pytest.fixture(scope="module")
def doctor():
    return runpy.run_path(str(HOOK))


def test_silent_outside_vault(tmp_path, subprocess_vault):
    _, env = subprocess_vault
    out = run_hook(str(tmp_path), env=env)
    assert out == ""


def test_silent_clean_vault(subprocess_vault):
    vault, env = subprocess_vault
    out = run_hook(str(vault), env=env)
    assert out == ""


def test_counts_wikilink_violations(subprocess_vault):
    vault, env = subprocess_vault
    (vault / "note.md").write_text("See [[foo.md]].")
    out = run_hook(str(vault), env=env)
    assert "wikilink-ext" in out


def test_counts_undated_files_in_journal(subprocess_vault):
    vault, env = subprocess_vault
    (vault / "Journal").mkdir()
    (vault / "Journal" / "untitled.md").write_text("hi")
    out = run_hook(str(vault), env=env)
    assert "undated-file" in out


def test_journal_index_is_not_counted_as_undated(subprocess_vault):
    vault, env = subprocess_vault
    (vault / "Journal").mkdir()
    (vault / "Journal" / "index.md").write_text("# Journal")
    assert run_hook(str(vault), env=env) == ""


def test_counts_yaml_errors(subprocess_vault):
    vault, env = subprocess_vault
    (vault / "note.md").write_text("---\ntitle: [broken\n---\nbody")
    out = run_hook(str(vault), env=env)
    assert "yaml-err" in out


def test_counts_needs_attention_entries(subprocess_vault):
    vault, env = subprocess_vault
    state_dir = vault / "Utility" / "obsidian-knowledge"
    state_dir.mkdir(parents=True)
    (state_dir / "needs-attention.md").write_text("# Needs Attention\n\n- [ ] foo\n- [ ] bar\n")
    out = run_hook(str(vault), env=env)
    assert "needs-attention" in out
    assert "2" in out


def test_skips_dotfolders(subprocess_vault):
    vault, env = subprocess_vault
    (vault / ".trash").mkdir()
    (vault / ".trash" / "junk.md").write_text("See [[foo.md]].")
    out = run_hook(str(vault), env=env)
    assert out == ""


def test_skips_sources_folders(subprocess_vault):
    vault, env = subprocess_vault
    (vault / "wiki" / "_sources").mkdir(parents=True)
    (vault / "wiki" / "_sources" / "orig.md").write_text("See [[foo.md]].")
    out = run_hook(str(vault), env=env)
    assert out == ""


def test_debounces_repeat_fire_within_session(subprocess_vault):
    """A SessionStart re-fire for the same session_id skips the re-scan.

    Guards against a compaction loop re-walking the vault and re-printing the
    digest back to back.
    """
    vault, env = subprocess_vault
    (vault / "note.md").write_text("See [[foo.md]].")
    session = {"session_id": f"s-{RUN_ID}-debounce"}

    out1 = run_hook(str(vault), env=env, payload=session)
    out2 = run_hook(str(vault), env=env, payload=session)

    assert "wikilink-ext" in out1
    assert out2 == ""  # second fire debounced → no re-scan output


def test_file_iterator_returns_only_markdown_and_skips_hidden_dirs(tmp_path, doctor):
    (tmp_path / "note.md").write_text("note")
    (tmp_path / "attachment.txt").write_text("text")
    (tmp_path / ".hidden").mkdir()
    (tmp_path / ".hidden" / "secret.md").write_text("hidden")

    assert set(doctor["iter_vault_md_files"](str(tmp_path))) == {str(tmp_path / "note.md")}


def test_scan_skips_markdown_that_becomes_unreadable(tmp_path, doctor, monkeypatch):
    note = tmp_path / "note.md"
    note.write_text("See [[bad.md]]")
    real_open = open

    def fail_note(path, *args, **kwargs):
        if str(path) == str(note):
            raise OSError("synthetic read failure")
        return real_open(path, *args, **kwargs)

    monkeypatch.setitem(doctor["scan_vault"].__globals__, "open", fail_note)
    assert doctor["scan_vault"](str(tmp_path)) == {
        "wikilink-ext": 0,
        "undated-file": 0,
        "yaml-err": 0,
    }


def test_ollama_probe_caches_health_and_reports_degradation(tmp_path, doctor, monkeypatch):
    lib_dir = str(Path(__file__).parents[1] / "lib")
    if lib_dir not in sys.path:
        sys.path.insert(0, lib_dir)
    from vault_index import indexer

    cache = tmp_path / "cache"
    monkeypatch.delenv("OBSIDIAN_KNOWLEDGE_SKIP_OLLAMA_PROBE", raising=False)
    monkeypatch.setattr(indexer, "default_cache_dir", lambda vault: cache)
    monkeypatch.setattr(indexer, "_ollama_probe", lambda api, model: (False, "backend unavailable"))

    warning = doctor["check_ollama"](str(tmp_path))
    assert warning == "obsidian-knowledge search is using basic ranking — backend unavailable."
    cached = json.loads((cache / "doctor-ollama.json").read_text())
    assert cached["ok"] is False

    monkeypatch.setattr(indexer, "_ollama_probe", lambda api, model: (True, "available"))
    assert doctor["check_ollama"](str(tmp_path)) is None
    monkeypatch.setattr(indexer, "_ollama_probe", lambda api, model: (_ for _ in ()).throw(AssertionError()))
    assert doctor["check_ollama"](str(tmp_path)) is None


def test_doctor_accepts_invalid_or_non_mapping_payload(subprocess_vault):
    vault, env = subprocess_vault
    (vault / "note.md").write_text("See [[bad.md]]")
    assert "wikilink-ext" in run_raw_hook(str(vault), "{", env)
    assert "wikilink-ext" in run_raw_hook(str(vault), "[]", env)


def test_doctor_prints_backend_warning_without_vault_findings(doctor, monkeypatch, capsys):
    monkeypatch.setattr(doctor["main"].__globals__["sys"], "stdin", io.StringIO("{}"))
    monkeypatch.setitem(doctor["main"].__globals__, "load_vault_roots", lambda: ["/vault"])
    monkeypatch.setitem(doctor["main"].__globals__, "find_containing_vault", lambda cwd, roots: "/vault")
    monkeypatch.setitem(doctor["main"].__globals__, "session_debounce", lambda payload, name: False)
    monkeypatch.setitem(doctor["main"].__globals__, "count_needs_attention", lambda root: 0)
    monkeypatch.setitem(
        doctor["main"].__globals__,
        "scan_vault",
        lambda root: {"wikilink-ext": 0, "undated-file": 0, "yaml-err": 0},
    )
    monkeypatch.setitem(doctor["main"].__globals__, "check_ollama", lambda root: "backend warning")

    doctor["main"]()
    assert capsys.readouterr().out == "backend warning\n"


def test_ollama_check_is_silent_when_optional_indexer_is_unavailable(tmp_path, doctor, monkeypatch):
    import builtins

    real_import = builtins.__import__

    def import_without_indexer(name, *args, **kwargs):
        if name == "vault_index.indexer":
            raise ImportError("optional indexer unavailable")
        return real_import(name, *args, **kwargs)

    monkeypatch.delenv("OBSIDIAN_KNOWLEDGE_SKIP_OLLAMA_PROBE", raising=False)
    monkeypatch.setattr(builtins, "__import__", import_without_indexer)
    assert doctor["check_ollama"](str(tmp_path)) is None


def test_ollama_check_still_reports_degradation_when_cache_is_unwritable(
    tmp_path,
    doctor,
    monkeypatch,
):
    from vault_index import indexer

    monkeypatch.delenv("OBSIDIAN_KNOWLEDGE_SKIP_OLLAMA_PROBE", raising=False)
    monkeypatch.setattr(indexer, "default_cache_dir", lambda vault: tmp_path / "cache")
    monkeypatch.setattr(indexer, "_ollama_probe", lambda api, model: (False, "offline"))
    monkeypatch.setattr(doctor["os"], "makedirs", lambda *args, **kwargs: (_ for _ in ()).throw(OSError()))

    assert doctor["check_ollama"](str(tmp_path)).endswith("offline.")
