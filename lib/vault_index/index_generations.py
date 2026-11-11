"""Publish complete index generations without replacing a reader's database."""

from __future__ import annotations

import os
from pathlib import Path

from pydantic import BaseModel, Field


class GenerationState(BaseModel):
    name: str = Field(pattern=r"^generation-[a-f0-9]+$")
    fingerprint: str = Field(min_length=1)


def active_cache(root: Path) -> Path | None:
    """Return published generation, or None before the first publication."""
    pointer = root / "current-generation"
    try:
        name = pointer.read_text().strip()
    except FileNotFoundError:
        return None
    if not name.startswith("generation-") or Path(name).name != name:
        raise ValueError("invalid index generation")
    return root / name


def generation_manifest(root: Path, *, keyword_only: bool) -> Path:
    return root / ("building-keyword.json" if keyword_only else "building-generation.json")


def publish_generation(root: Path, generation: Path, *, keyword_only: bool = False) -> None:
    """Atomic pointer swap; existing connections retain their original generation."""
    if generation.parent != root or not generation.name.startswith("generation-"):
        raise ValueError("invalid index generation")
    temporary = root / "current-generation.next"
    with temporary.open("w") as output:
        output.write(generation.name + "\n")
        output.flush()
        os.fsync(output.fileno())
    temporary.replace(root / "current-generation")
    generation_manifest(root, keyword_only=keyword_only).unlink(missing_ok=True)


def prepare_generation(root: Path, fingerprint: str, *, keyword_only: bool = False) -> tuple[Path, bool]:
    """Resume an unpublished generation; never modify the published generation."""
    import uuid

    manifest = generation_manifest(root, keyword_only=keyword_only)
    try:
        state = GenerationState.model_validate_json(manifest.read_text())
    except FileNotFoundError:
        state = None
    if state is not None and state.fingerprint == fingerprint and root / state.name != active_cache(root):
        return root / state.name, False
    generation = root / ("generation-" + uuid.uuid4().hex)
    generation.mkdir()
    temporary = manifest.with_suffix(".next")
    temporary.write_text(GenerationState(name=generation.name, fingerprint=fingerprint).model_dump_json())
    temporary.replace(manifest)
    return generation, True
