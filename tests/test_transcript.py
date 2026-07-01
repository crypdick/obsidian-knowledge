"""Unit tests for hooks/lib/transcript.py."""

import json

from hookslib.transcript import count_user_messages, iter_tool_uses


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


def test_count_user_messages_none_when_unavailable(tmp_path):
    assert count_user_messages(None) is None
    assert count_user_messages(str(tmp_path / "nope.jsonl")) is None


def test_count_user_messages_counts_only_genuine(tmp_path):
    f = tmp_path / "t.jsonl"
    f.write_text(
        "\n".join(
            json.dumps(e)
            for e in [
                {"type": "user", "message": {"role": "user", "content": "hello"}},
                # tool_result carrier — not a genuine user message
                {"type": "user", "message": {"content": [
                    {"type": "tool_result", "tool_use_id": "t1", "content": "ok"},
                ]}},
                # meta entry — excluded
                {"type": "user", "isMeta": True,
                 "message": {"content": "system reminder"}},
                {"type": "assistant", "message": {"content": [
                    {"type": "text", "text": "hi"}]}},
                # multimodal user message (list, no tool_result) — counts
                {"type": "user", "message": {"content": [
                    {"type": "text", "text": "second"}]}},
            ]
        )
        + "\n"
    )
    assert count_user_messages(str(f)) == 2
