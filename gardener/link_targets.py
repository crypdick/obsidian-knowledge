"""Conservative filesystem identity for index links and coverage checks."""

from pathlib import Path

from gardener.io import visible_path


def resolve_target(vault: Path, folder: Path, target: str) -> Path | None:
    """Resolve root, source folder, then ancestors; first existing file wins.

    Validate before resolution so an unsafe or symlink-shadowed target never
    receives credit through a different base. No basename or alias guessing.
    """
    bases = (vault, folder, *(vault / parent for parent in folder.relative_to(vault).parents))
    for base in dict.fromkeys(bases):
        for name in (target, target + ".md"):
            relative = (base.relative_to(vault) / name).as_posix()
            path = visible_path(vault, relative)
            if path.is_file():
                return path
    return None
