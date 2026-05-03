"""Unit tests for hooks/lib/transcript.py."""

import json

from lib.transcript import iter_tool_uses


def test_missing_file_yields_nothing(tmp_path):
    assert list(iter_tool_uses(str(tmp_path / "nope.jsonl"))) == []


def test_extracts_tool_uses(tmp_path):
    f = tmp_path / "t.jsonl"
    f.write_text(json.dumps({
        "type": "assistant",
        "message": {"role": "assistant", "content": [
            {"type": "tool_use", "id": "t1", "name": "Write",
             "input": {"file_path": "/v/a.md", "content": "hi"}},
            {"type": "text", "text": "ignored"},
        ]},
    }) + "\n")
    uses = list(iter_tool_uses(str(f)))
    assert len(uses) == 1
    assert uses[0]["name"] == "Write"
    assert uses[0]["input"]["file_path"] == "/v/a.md"


def test_skips_malformed_lines(tmp_path):
    f = tmp_path / "t.jsonl"
    f.write_text("not json\n" + json.dumps({
        "type": "assistant",
        "message": {"content": [
            {"type": "tool_use", "id": "t2", "name": "Edit", "input": {}},
        ]},
    }) + "\n")
    uses = list(iter_tool_uses(str(f)))
    assert len(uses) == 1
    assert uses[0]["name"] == "Edit"


def test_handles_non_list_content(tmp_path):
    f = tmp_path / "t.jsonl"
    f.write_text(json.dumps({"message": {"content": "string"}}) + "\n")
    assert list(iter_tool_uses(str(f))) == []
