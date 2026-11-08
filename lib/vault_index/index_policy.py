"""Index admission shared by discovery, notifications, and per-file updates."""

from pathlib import Path

from lib.vault_index.config import VaultIndexConfig
from lib.vault_index.filters import path_passes
from lib.vault_index.vault_listing import visible_name


def index_path(vault: Path, relative: str) -> Path:
    """Validate lexical ownership, including paths whose old entries need removal."""
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError("index path escapes vault; expected a vault-relative path")
    return vault / path


def indexable(vault: Path, relative: str, config: VaultIndexConfig) -> bool:
    """Only visible, confined, nonsymlink Markdown files may enter the index."""
    path = index_path(vault, relative)
    if path.suffix != ".md" or not all(visible_name(part) for part in Path(relative).parts):
        return False
    current = vault
    for part in Path(relative).parts:
        current = current / part
        if current.is_symlink():
            return False
    return (
        path.is_file()
        and path.resolve().is_relative_to(vault.resolve())
        and path_passes(relative, config.index)
    )
