#!/usr/bin/env python3
"""Prek hook to enforce timeless comments.

Philosophy: Comments should describe *what* code does and *why*, not narrate
repository history. Temporal language that centers chronology instead of
current behavior makes comments age poorly and obscures the code's present
intent.

Detects:
- Temporal keywords in inline comments and docstrings (see ``TEMPORAL_KEYWORDS``)

Allowed:
- Lines annotated with ``# allow: timeless-comments``
- Lines containing ``# temporal-ok``
- Lines containing the hourglass emoji (U+23F3)
- Lines with ``TODO`` or ``FIXME`` (inherently time-bound by nature)

Exit codes:
  0 - All checks passed
  1 - Violations found
"""

import ast
import io
import re
import sys
import tokenize
from pathlib import Path

# Keywords that indicate temporal language in comments
TEMPORAL_KEYWORDS = [
    r"\blegacy\b",
    r"\bfallback\b",
    r"\bold\b",
    r"\bobsolete\b",
    r"\bhas been\b",
    r"\bused to\b",
    r"\bis being\b",
    r"\bnew\b",
    r"\bprevious\b",
    r"\bprior\b",
    r"\bdeprecate[ds]?\b",
    r"\boriginal\b",
    r"\brefactor\b",
    r"\breplace[ds]?\b",
    r"\bmigrate[ds]?\b",
    r"\bupgrade[ds]?\b",
    r"\bno longer\b",
    r"\bunused\b",
    r"\bhistoric\b",
    r"\bremoved\b",
    r"\bswitch\b",
    r"\bcompatibility\b",
    r"\bcompatible\b",
    r"\bformer\b",
    r"\bis now\b",
    r"\bwere removed\b",
    r"\bfor now\b",
    r"\bin favor of\b",
    r"\bbut wait\b",
    r"\bactually,\b",
    r"\bwait,\b",
    r"\bah!",
]


_ALLOW = re.compile(r"#\s*allow:\s*timeless-comments(?![\w-])", re.IGNORECASE)
_TASK_MARKER = re.compile(r"\b(?:TODO|FIXME)\b", re.IGNORECASE)
_TEMPORAL_PATTERNS = [re.compile(keyword, re.IGNORECASE) for keyword in TEMPORAL_KEYWORDS]


def extract_comments(content: str, filename: str = "<unknown>") -> list[tuple[int, str]]:
    """Extract comment tokens and docstring source, excluding neighboring code."""
    comments: set[tuple[int, str]] = set()
    try:
        for token in tokenize.generate_tokens(io.StringIO(content).readline):
            if token.type == tokenize.COMMENT:
                comments.add((token.start[0], token.string))
    except (IndentationError, tokenize.TokenError):
        pass  # Keep comments read before a syntax error; Ruff reports the error.

    try:
        tree = ast.parse(content, filename=filename)
    except SyntaxError:
        return sorted(comments)

    containers = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
    for node in ast.walk(tree):
        if not isinstance(node, containers) or not node.body:
            continue
        first = node.body[0]
        if not (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            continue
        segment = ast.get_source_segment(content, first.value)
        if segment is not None:
            comments.update(enumerate(segment.splitlines(), start=first.value.lineno))
    return sorted(comments)


def check_timeless_comments(file_path: Path) -> list[tuple[int, str, str]]:
    """Return (line, comment, keyword pattern), with at most one finding per line."""
    try:
        content = file_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return []  # Ruff owns encoding diagnostics.
    comments = extract_comments(content, str(file_path))
    exempt_lines = {line for line, comment in comments if _ALLOW.search(comment)}
    violations: dict[int, tuple[int, str, str]] = {}
    for line_num, comment in comments:
        if (
            line_num in exempt_lines
            or "\u23f3" in comment
            or re.search(r"\btemporal-ok\b", comment, re.IGNORECASE)
            or _TASK_MARKER.search(comment)
        ):
            continue
        for pattern in _TEMPORAL_PATTERNS:
            if pattern.search(comment):
                violations.setdefault(line_num, (line_num, comment.strip(), pattern.pattern))
                break
    return list(violations.values())


def main(filenames: list[str]) -> int:
    """Run timeless comment check on provided files."""
    exit_code = 0

    for filename in filenames:
        file_path = Path(filename)

        # Only check Python files
        if file_path.suffix != ".py":
            continue

        # Skip if file doesn't exist (might be deleted)
        if not file_path.exists():
            continue

        violations = check_timeless_comments(file_path)

        if violations:
            exit_code = 1

            for line_num, _comment_text, keyword in violations:
                print(
                    f"{file_path}:{line_num}: Temporal keyword '{keyword}' "
                    f"in comment — rewrite to describe current behavior, "
                    f"not history (or mark with # temporal-ok)"
                )

    return exit_code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
