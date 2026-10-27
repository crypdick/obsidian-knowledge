"""Configured creation defaults are shared without executing template code."""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml

from lib.vault_index.mcp_server import create_server
from lib.vault_index.vault_files import patch_vault_file, write_vault_file

ROOT = Path(__file__).parents[1]
DECLARATION = 'const creationDefaults = /* obsidian-knowledge:creation-defaults */ {"created":"{{now}}"};'


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    config = Path(os.environ["OBSIDIAN_KNOWLEDGE_CONFIG"])
    config.parent.mkdir(exist_ok=True)
    config.write_text("note_creation:\n  template: settings/router.md\n  exclude: [scaffolds]\n")
    template = tmp_path / "settings/router.md"
    template.parent.mkdir(parents=True)
    template.write_text(f"<%*\n{DECLARATION}\nthrow new Error('must not execute');\n%>\n")
    return tmp_path


def test_new_note_gets_current_created_without_other_timestamps(vault: Path) -> None:
    before = datetime.now(UTC).replace(microsecond=0)
    content = b"# A note\n\nLiteral $() and [[links]].\n"
    target = write_vault_file(vault, Path("wiki/new.md"), content)
    text = target.read_text()
    metadata = yaml.safe_load(text.split("---", 2)[1])
    assert before <= datetime.fromisoformat(metadata["created"]) <= datetime.now(UTC)
    assert set(metadata) == {"created"}
    assert target.read_bytes().endswith(content)
    assert "creationDefaults" not in text


@pytest.mark.parametrize("value", ["2024-01-02", "'custom creation date'", "null", "''"])
def test_supplied_created_is_preserved_byte_for_byte(vault: Path, value: str) -> None:
    content = f"---\n# keep this comment\ncreated: {value}\ntags: [example]\n---\n# Body\n".encode()
    target = write_vault_file(vault, Path("new.md"), content)
    assert target.read_bytes() == content


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
@pytest.mark.parametrize("bom", [b"", b"\xef\xbb\xbf"])
@pytest.mark.parametrize("closing", ["---", "..."])
def test_existing_yaml_and_body_format_are_preserved(vault, newline, bom, closing):
    content = (
        bom
        + newline.join(
            ["---", "# comment", "aliases: [Example]", "updated: 2020-01-01", closing, "# Body", ""]
        ).encode()
    )
    target = write_vault_file(vault, Path("new.md"), content)
    written = target.read_bytes()
    assert written.startswith(bom + f"---{newline}created: ".encode())
    assert written.endswith(content[len(bom + f"---{newline}".encode()) :])
    assert written.count(b"updated:") == 1


@pytest.mark.parametrize("content", [b"---\n---\n# Body", b"---\n# comment\n---\n# Body"])
def test_empty_frontmatter_gets_created(vault, content):
    target = write_vault_file(vault, Path("new.md"), content)
    assert target.read_bytes().startswith(b"---\ncreated:")
    assert target.read_bytes().endswith(b"# Body")


def test_bom_without_frontmatter_is_preserved(vault):
    target = write_vault_file(vault, Path("new.md"), b"\xef\xbb\xbf# Body\r\n")
    assert target.read_bytes().startswith(b"\xef\xbb\xbf---\r\ncreated:")
    assert target.read_bytes().endswith(b"# Body\r\n")


def test_edit_and_patch_never_apply_creation_defaults(vault):
    target = vault / "existing.md"
    target.write_bytes(b"# Existing\n")
    write_vault_file(vault, Path("existing.md"), b"# Edited\n", replace=True)
    patch_vault_file(vault, Path("existing.md"), "Edited", "Patched")
    assert target.read_bytes() == b"# Patched\n"


def test_replace_flag_on_missing_note_still_initializes(vault):
    target = write_vault_file(vault, Path("new.md"), b"# Body", replace=True)
    assert target.read_bytes().startswith(b"---\ncreated:")


@pytest.mark.parametrize("path", ["scaffolds/example.md", "image.bin"])
def test_templates_and_non_markdown_bytes_are_untouched(vault, path):
    content = b"\xff\x00 raw bytes"
    target = write_vault_file(vault, Path(path), content)
    assert target.read_bytes() == content


@pytest.mark.parametrize("template", [None, "<%*\n// legacy template\n%>\n"])
def test_vaults_without_declaration_keep_exact_write_contract(tmp_path, template):
    if template is not None:
        meta = tmp_path / "settings/router.md"
        meta.parent.mkdir(parents=True)
        meta.write_text(template)
    content = b"# Body"
    assert write_vault_file(tmp_path, Path("new.md"), content).read_bytes() == content


@pytest.mark.parametrize(
    "declaration",
    [
        DECLARATION + "\n" + DECLARATION,
        'const creationDefaults = /* obsidian-knowledge:creation-defaults */ ["invalid"];',
        "/* obsidian-knowledge:creation-defaults */ malformed",
        "const creationDefaults = /* obsidian-knowledge:creation-defaults */ {bad};",
    ],
)
def test_invalid_policy_fails_before_creating_target_directories(vault, declaration):
    (vault / "settings/router.md").write_text(declaration)
    with pytest.raises(ValueError):
        write_vault_file(vault, Path("wiki/new.md"), b"# Body")
    assert not (vault / "wiki").exists()


@pytest.mark.parametrize("content", [b"---\n[bad: yaml\n---\nBody", b"---\n- list\n---\nBody", b"---\nBody"])
def test_invalid_frontmatter_does_not_create_note(vault, content):
    with pytest.raises(ValueError):
        write_vault_file(vault, Path("new.md"), content)
    assert not (vault / "new.md").exists()


def test_template_cannot_escape_vault(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    vault = tmp_path / "vault"
    vault.mkdir()
    config = Path(os.environ["OBSIDIAN_KNOWLEDGE_CONFIG"])
    config.parent.mkdir(exist_ok=True)
    config.write_text("note_creation:\n  template: settings/router.md\n")
    (vault / "settings").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="template resolves outside"):
        write_vault_file(vault, Path("new.md"), b"# Body")
    assert not (vault / "new.md").exists()


def test_cli_initializes_without_obsidian_running(vault):
    result = subprocess.run(
        [sys.executable, "-m", "lib.vault_index.cli", "write", "wiki/new.md", "--vault", str(vault)],
        input="# Headless note\n",
        text=True,
        capture_output=True,
        cwd=ROOT,
    )
    assert result.returncode == 0, result.stderr
    assert (vault / "wiki/new.md").read_bytes().startswith(b"---\ncreated:")


def test_mcp_initializes_once_and_preserves_created_during_edit(vault):
    async def exercise():
        server = create_server(vault)
        await server.call_tool("vault_write", {"path": "wiki/new.md", "content": "# New\n"})
        target = vault / "wiki/new.md"
        baseline = target.read_bytes()
        assert baseline.startswith(b"---\ncreated:")
        await server.call_tool(
            "vault_write",
            {
                "path": "wiki/new.md",
                "content": baseline.decode().replace("# New", "# Edited"),
                "replace": True,
            },
        )
        assert target.read_bytes() == baseline.replace(b"# New", b"# Edited")

    asyncio.run(exercise())


def test_arbitrary_metadata_names_and_nested_defaults_are_vault_owned(vault):
    (vault / "settings/router.md").write_text(
        "const metadata = /* obsidian-knowledge:creation-defaults */ "
        '{"recorded_at":"{{now}}","category":"reference","tags":["example"],'
        '"custom":{"enabled":true,"count":3},"optional":null};'
    )
    target = write_vault_file(vault, Path("new.md"), b"---\ncategory: custom\n---\n# Body")
    metadata = yaml.safe_load(target.read_text().split("---", 2)[1])
    assert datetime.fromisoformat(metadata["recorded_at"]).utcoffset() is not None
    assert metadata["category"] == "custom"
    assert metadata["tags"] == ["example"]
    assert metadata["custom"] == {"enabled": True, "count": 3}
    assert metadata["optional"] is None
    assert "created" not in metadata


@pytest.mark.parametrize(
    "settings",
    [
        "note_creation:\n  template: /outside.md\n",
        "note_creation:\n  template: ../outside.md\n",
        "note_creation:\n  template: ''\n",
        "note_creation:\n  exclude: [/outside]\n",
        "note_creation:\n  exclude: [../outside]\n",
    ],
)
def test_invalid_creation_paths_are_rejected(vault, settings):
    Path(os.environ["OBSIDIAN_KNOWLEDGE_CONFIG"]).write_text(settings)
    with pytest.raises(ValueError, match="vault-relative"):
        write_vault_file(vault, Path("new.md"), b"# Body")
    assert not (vault / "new.md").exists()


def test_configured_template_without_declaration_is_rejected(vault):
    (vault / "settings/router.md").write_text("# Ordinary template\n")
    with pytest.raises(ValueError, match="marked JSON declaration"):
        write_vault_file(vault, Path("new.md"), b"# Body")


def test_configured_template_must_exist(vault):
    Path(os.environ["OBSIDIAN_KNOWLEDGE_CONFIG"]).write_text("note_creation:\n  template: missing.md\n")
    with pytest.raises(FileNotFoundError):
        write_vault_file(vault, Path("new.md"), b"# Body")


def test_creating_selected_template_does_not_try_to_apply_it(vault):
    Path(os.environ["OBSIDIAN_KNOWLEDGE_CONFIG"]).write_text(
        "note_creation:\n  template: future-template.md\n"
    )
    content = b"# A template, not a note"
    assert write_vault_file(vault, Path("future-template.md"), content).read_bytes() == content


def test_empty_defaults_are_a_noop(vault):
    (vault / "settings/router.md").write_text("const data = /* obsidian-knowledge:creation-defaults */ {};")
    content = b"# Note"
    assert write_vault_file(vault, Path("new.md"), content).read_bytes() == content


def test_null_template_explicitly_disables_creation_defaults(vault):
    Path(os.environ["OBSIDIAN_KNOWLEDGE_CONFIG"]).write_text(
        "note_creation:\n  template: null\n  exclude: []\n"
    )
    content = b"# Note"
    assert write_vault_file(vault, Path("new.md"), content).read_bytes() == content


def test_per_vault_legacy_config_is_not_an_implicit_fallback(tmp_path):
    legacy = tmp_path / ".claude/obsidian-knowledge.yaml"
    legacy.parent.mkdir()
    legacy.write_text("note_creation:\n  template: missing.md\n")
    content = b"# Note"
    assert write_vault_file(tmp_path, Path("new.md"), content).read_bytes() == content
