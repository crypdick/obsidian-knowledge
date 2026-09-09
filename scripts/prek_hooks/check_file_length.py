#!/usr/bin/env python3
"""Prek hook to enforce file length limits.

Philosophy: Large files are harder to understand, test, and review.  Keeping
files under a logical-line budget encourages modularity and separation of
concerns.

Logical lines of code (LLOC) are lines that are not empty, not comments, and
not part of docstrings or standalone string literals.

Arguments:
  --max-lines N   Maximum allowed logical lines per file (default: 400)

Allowed:
- Files with ``# allow: file-length`` in the first 5 lines

Exit codes:
  0 - All checks passed
  1 - Violations found
"""

import argparse
import ast
import io
import re
import sys
import tokenize
from pathlib import Path

_ALLOW = re.compile(r"#\s*allow:\s*file-length(?![\w-])", re.IGNORECASE)


def count_logical_lines(filepath: Path) -> int:
    """Count physical lines containing code, excluding standalone strings.

    Continuation lines count toward the budget. AST byte offsets let us remove
    standalone strings while preserving code that shares their source lines.
    """
    try:
        content = filepath.read_text(encoding="utf-8")
        tree = ast.parse(content, filename=str(filepath))
    except (SyntaxError, UnicodeDecodeError):
        return 0  # Ruff owns syntax and encoding diagnostics.

    lines = content.encode("utf-8").splitlines(keepends=True)
    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            continue
        end_line = node.end_lineno or node.lineno
        for line_num in range(node.lineno, end_line + 1):
            line = lines[line_num - 1]
            start = node.col_offset if line_num == node.lineno else 0
            end = node.end_col_offset if line_num == end_line else len(line.rstrip(b"\r\n"))
            if end is None:
                end = len(line.rstrip(b"\r\n"))
            lines[line_num - 1] = line[:start] + b" " * (end - start) + line[end:]

    code = b"".join(lines).decode("utf-8")
    ignored_tokens = {
        tokenize.COMMENT,
        tokenize.NL,
        tokenize.NEWLINE,
        tokenize.INDENT,
        tokenize.DEDENT,
        tokenize.ENDMARKER,
    }
    code_lines: set[int] = set()
    for token in tokenize.generate_tokens(io.StringIO(code).readline):
        if token.type not in ignored_tokens and token.string.strip() and token.string != ";":
            code_lines.update(
                line for line in range(token.start[0], token.end[0] + 1) if lines[line - 1].strip()
            )
    return len(code_lines)


def check_file_length(filepath: Path, max_lines: int) -> tuple[int, str] | None:
    """Check whether *filepath* exceeds *max_lines* logical lines.

    Returns ``(lloc, message)`` on violation or ``None`` if the file is fine.
    """
    lloc = count_logical_lines(filepath)
    if lloc > max_lines:
        return (
            lloc,
            (
                f"File has {lloc} logical lines (limit {max_lines}) "
                f"— split into smaller, focused modules "
                f"(extract cohesive behavior into a domain-focused module or composed collaborators)"
            ),
        )
    return None


def main(filenames: list[str] | None = None) -> int:
    """Run file-length check on provided files."""
    parser = argparse.ArgumentParser(description="Check for files exceeding logical line count limit")
    parser.add_argument("filenames", nargs="*", help="Filenames to check")
    parser.add_argument(
        "--max-lines",
        type=int,
        default=400,
        help="Maximum allowed logical lines per file (default: 400)",
    )
    args = parser.parse_args(filenames)
    if args.max_lines < 1:
        parser.error("--max-lines must be a positive integer")

    exit_code = 0

    for filename in args.filenames:
        filepath = Path(filename)

        if filepath.suffix != ".py" or not filepath.exists():
            continue

        # Tokenization prevents a marker inside a string from exempting the file.
        try:
            with filepath.open(encoding="utf-8") as source:
                exempt = False
                for token in tokenize.generate_tokens(source.readline):
                    if token.start[0] > 5:
                        break
                    if token.type == tokenize.COMMENT and _ALLOW.search(token.string):
                        exempt = True
                        break
        except (UnicodeDecodeError, IndentationError, tokenize.TokenError):
            continue  # Ruff owns malformed source diagnostics.
        if exempt:
            continue

        result = check_file_length(filepath, args.max_lines)

        if result is not None:
            _lloc, message = result
            exit_code = 1
            print(f"{filename}:1: {message}")

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
