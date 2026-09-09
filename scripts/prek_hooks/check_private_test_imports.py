#!/usr/bin/env python3
"""Prek hook to forbid tests from importing private first-party symbols.

Philosophy: tests should verify *public behaviour*, not private implementation
shape. Importing a leading-underscore name from a first-party package into a
test couples that test to internal structure: it breaks on harmless refactors
and, worse, keeps dead private code alive past the point the public surface
stopped needing it. Drive the public entry point instead and assert on its
observable result.

Detects:
- ``from <first_party>... import _private`` in test files, including the
  per-name form inside a parenthesised multi-line import

First-party packages are auto-detected from the repository layout (top-level
or ``src/`` directories containing ``__init__.py``, plus Python modules). Pass ``--package NAME``
(repeatable) to override detection.

Allowed:
- Public names (no leading underscore) and dunders (``__version__``)
- Private imports from non-first-party modules (test-support helpers, stdlib,
  third-party packages)
- A name annotated with ``# allow: private-test-imports`` (narrow carve-out for
  a private whose only effect is an external-process side channel with no
  public observable)

Exit codes:
  0 - All checks passed
  1 - Violations found
"""

from __future__ import annotations

import argparse
import ast
import io
import re
import sys
import tokenize
from pathlib import Path

_ALLOW = re.compile(r"#\s*allow:\s*private-test-imports(?![\w-])", re.IGNORECASE)
_SKIP_DIRS = frozenset(
    {
        "tests",
        "test",
        "scripts",
        "docs",
        "doc",
        "examples",
        "build",
        "dist",
        "node_modules",
        "__pycache__",
    }
)


def detect_first_party_packages(root: Path) -> set[str]:
    """Return the set of importable top-level first-party package names.

    First-party names include Python modules and directories containing
    ``__init__.py`` at the repo root or under ``src/``. Tooling and test directories are excluded. When the
    repo ships no importable package (e.g. a docs-only repo) the result is empty
    and the hook flags nothing.
    """
    packages: set[str] = set()
    search_roots = [root, root / "src"]
    for search_root in search_roots:
        if not search_root.is_dir():
            continue
        for child in search_root.iterdir():
            if child.name.startswith("."):
                continue
            if child.is_file() and child.suffix == ".py":
                if (
                    child.stem.isidentifier()
                    and child.stem not in {"__init__", "conftest", "setup"}
                    and not is_test_file(Path(child.name))
                ):
                    packages.add(child.stem)
                continue
            if child.name in _SKIP_DIRS:
                continue
            if child.name.isidentifier() and (child / "__init__.py").is_file():
                packages.add(child.name)
    return packages


class PrivateImportVisitor(ast.NodeVisitor):
    """AST visitor flagging imports of private first-party symbols."""

    def __init__(self, file_content: str, first_party: set[str]) -> None:
        self.exempt_lines = {
            token.start[0]
            for token in tokenize.generate_tokens(io.StringIO(file_content).readline)
            if token.type == tokenize.COMMENT and _ALLOW.search(token.string)
        }
        self.first_party = first_party
        self.violations: list[tuple[int, str, str]] = []

    def _is_first_party(self, module: str) -> bool:
        """Return True when *module*'s top component is a first-party package."""
        top = module.split(".", 1)[0]
        return top in self.first_party

    def _is_private(self, name: str) -> bool:
        """Return True when imported *name* is a private symbol.

        A leading underscore marks private. A ``__dunder__`` (leading AND
        trailing double underscore) is public API and is not flagged; a
        name-mangled ``__thing`` (no trailing dunder) stays private.
        """
        return name.startswith("_") and not (name.startswith("__") and name.endswith("__"))

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        module = node.module or ""
        if node.level == 0 and self._is_first_party(module):
            for alias in node.names:
                if self._is_private(alias.name) and alias.lineno not in self.exempt_lines:
                    self.violations.append((alias.lineno, alias.name, module))
        self.generic_visit(node)


def find_private_imports(
    content: str,
    first_party: set[str],
    filename: str = "<unknown>",
) -> list[tuple[int, str, str]]:
    """Return ``(lineno, name, module)`` for each private first-party import."""
    try:
        tree = ast.parse(content, filename=filename)
    except (SyntaxError, ValueError):
        return []
    visitor = PrivateImportVisitor(content, first_party)
    visitor.visit(tree)
    return visitor.violations


def is_test_file(file_path: Path) -> bool:
    """Only test files are subject to the convention."""
    return (
        bool({"test", "tests"}.intersection(file_path.parts[:-1]))
        or file_path.name.startswith("test_")
        or file_path.name.endswith("_test.py")
    )


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Forbid private first-party imports in tests")
    parser.add_argument(
        "--package",
        action="append",
        default=[],
        help="First-party package name to guard (repeatable; overrides auto-detection)",
    )
    parser.add_argument("filenames", nargs="*")
    args = parser.parse_args(argv)

    first_party = set(args.package) or detect_first_party_packages(Path.cwd())
    if not first_party:
        return 0

    exit_code = 0
    for filename in args.filenames:
        file_path = Path(filename)
        if file_path.suffix != ".py" or not is_test_file(file_path) or not file_path.exists():
            continue
        try:
            content = file_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue  # Ruff owns encoding diagnostics.
        for line_num, name, module in find_private_imports(content, first_party, str(file_path)):
            exit_code = 1
            print(
                f"{file_path}:{line_num}: test imports private '{name}' from first-party "
                f"'{module}' — drive the public entry point that exercises it and assert on "
                f"observable output (or annotate with # allow: private-test-imports)"
            )

    return exit_code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
