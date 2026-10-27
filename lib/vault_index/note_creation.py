"""Apply explicitly configured, vault-owned metadata defaults to new notes."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, JsonValue, RootModel, field_validator
from vault_preferences import load_preferences

# NOTE: docs/configuration.md, Note creation, defines this opt-in template contract.
POLICY_MARKER = "/* obsidian-knowledge:creation-defaults */"


class NoteCreationConfig(BaseModel):
    """All template selection and exclusions belong to the vault configuration."""

    model_config = ConfigDict(extra="forbid")
    template: Path | None = None
    exclude: tuple[Path, ...] = ()

    @field_validator("template")
    @classmethod
    def relative_template(cls, value: Path | None) -> Path | None:
        if value is not None and (value.is_absolute() or value == Path(".") or ".." in value.parts):
            raise ValueError("creation template must be a vault-relative file path")
        return value

    @field_validator("exclude")
    @classmethod
    def relative_exclusions(cls, values: tuple[Path, ...]) -> tuple[Path, ...]:
        for value in values:
            if value.is_absolute() or ".." in value.parts:
                raise ValueError("creation exclusions must be vault-relative paths")
        return values


class VaultCreationSettings(BaseModel):
    """Read only the creation section of the shared vault configuration."""

    note_creation: NoteCreationConfig = Field(default_factory=NoteCreationConfig)


class CreationDefaults(RootModel[dict[str, JsonValue]]):
    """Parse arbitrary JSON metadata defaults rather than prescribing note fields."""


class NoteFrontmatter(BaseModel):
    """Parse note YAML at the boundary without rewriting unrelated properties."""

    model_config = ConfigDict(extra="allow")


def load_creation_config() -> NoteCreationConfig:
    """Keep creation disabled unless shared preferences select a relative template."""
    return VaultCreationSettings.model_validate(load_preferences().root).note_creation


def load_creation_defaults(vault_root: Path, relative_template: Path) -> CreationDefaults:
    """Read a confined template's declarative metadata without executing its code."""
    template = (vault_root / relative_template).resolve()
    if not template.is_relative_to(vault_root.resolve()):
        raise ValueError("creation template resolves outside the vault")
    source = template.read_text(encoding="utf-8")
    declarations = re.findall(
        r"/\* obsidian-knowledge:creation-defaults \*/[ \t]*(.+);[ \t]*$",
        source,
        flags=re.MULTILINE,
    )
    if source.count(POLICY_MARKER) != 1 or len(declarations) != 1:
        raise ValueError("creation template must contain exactly one marked JSON declaration")
    timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
    return CreationDefaults.model_validate_json(declarations[0].replace("{{now}}", timestamp))


def initialize_note(vault_root: Path, relative_path: Path, content: bytes) -> bytes:
    """Merge missing defaults once, preserving supplied metadata and body bytes."""
    if relative_path.suffix.lower() != ".md":
        return content
    config = load_creation_config()
    if config.template is None or relative_path == config.template:
        return content
    if any(relative_path.is_relative_to(excluded) for excluded in config.exclude):
        return content
    defaults = load_creation_defaults(vault_root, config.template)
    text = content.decode("utf-8-sig")
    bom = "\ufeff" if content.startswith(b"\xef\xbb\xbf") else ""
    newline = "\r\n" if "\r\n" in text else "\n"
    frontmatter = re.match(
        r"\A(?P<opening>---[ \t]*\r?\n)(?P<yaml>.*?)(?P<closing>^(?:---|\.\.\.)[ \t]*(?:\r?\n|\Z))",
        text,
        flags=re.MULTILINE | re.DOTALL,
    )
    if frontmatter:
        try:
            raw = yaml.safe_load(frontmatter["yaml"])
        except yaml.YAMLError as exc:
            raise ValueError("new note has malformed YAML frontmatter") from exc
        metadata = NoteFrontmatter.model_validate({} if raw is None else raw)
    elif re.match(r"\A---[ \t]*(?:\r?\n|\Z)", text):
        raise ValueError("new note has unclosed YAML frontmatter")
    else:
        metadata = NoteFrontmatter()

    additions = {key: value for key, value in defaults.root.items() if key not in metadata.model_fields_set}
    if not additions:
        return content
    header = yaml.safe_dump(additions, allow_unicode=True, sort_keys=False).replace("\n", newline)
    if frontmatter:
        offset = frontmatter.end("opening")
        result = text[:offset] + header + text[offset:]
    else:
        result = f"---{newline}{header}---{newline}{newline}{text}"
    return (bom + result).encode("utf-8")
