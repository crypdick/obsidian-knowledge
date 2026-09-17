#!/usr/bin/env python3
"""Check static import boundaries documented in docs/ARCHITECTURE.md.

Inspect imports inside functions and TYPE_CHECKING blocks too. Subprocess source
strings and dynamic loaders are reviewed manually; this is a static import gate.
"""

from __future__ import annotations

import argparse
import ast
from pathlib import Path


def imported_modules(node: ast.AST, path: Path) -> list[str]:
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names]
    if not isinstance(node, ast.ImportFrom):
        return []
    module = node.module or ""
    if node.level:
        parts = path.parent.parts
        if node.level > len(parts):
            return ["<invalid-relative-import>"]
        prefix = parts[: len(parts) - node.level + 1]
        module = ".".join((*prefix, module)).rstrip(".")
    return [module, *(f"{module}.{alias.name}" for alias in node.names)]


def forbidden(path: Path, module: str) -> bool:
    top = module.split(".")[0]
    if top == "<invalid-relative-import>":
        return True
    if path.parts[0] == "lib":
        if path.as_posix() == "lib/vault_index/primer.py" and (
            module == "hookslib.repo_memory" or module.startswith("hookslib.repo_memory.")
        ):
            return False
        return top in {"hooks", "hookslib", "vault_registry"}
    if path.parts[:2] == ("hooks", "hookslib"):
        return top in {"lib", "vault_index"}
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    root = parser.parse_args().root
    failed = False
    for package in ("lib", "hooks"):
        for source in sorted((root / package).rglob("*.py")):
            path = source.relative_to(root)
            try:
                tree = ast.parse(source.read_text(encoding="utf-8"))
            except (SyntaxError, UnicodeDecodeError) as error:
                print(f"{path}:1: cannot inspect source: {error} -- fix syntax/encoding")
                failed = True
                continue
            for node in ast.walk(tree):
                violations = [module for module in imported_modules(node, path) if forbidden(path, module)]
                if violations:
                    print(
                        f"{path}:{node.lineno}: forbidden import {violations[0]} "
                        "-- follow docs/ARCHITECTURE.md import boundaries"
                    )
                    failed = True
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
