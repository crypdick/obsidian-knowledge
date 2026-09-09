#!/usr/bin/env python3
"""Flag bare handlers and broad handlers without a direct raise or logging call.

Recognizes Exception and BaseException, including builtins-qualified names and
exception tuples. Logging uses receiver names logging, log, logger, or names
ending in _logger; this is a syntax heuristic, not control-flow or type analysis.
Narrow exception handlers may intentionally suppress an expected error.
Exempt a handler with ``# allow: exception-handling`` on its ``except`` line.
"""

import ast
import io
import re
import sys
import tokenize
from pathlib import Path

_ALLOW = re.compile(r"#\s*allow:\s*exception-handling(?![\w-])", re.IGNORECASE)
_BROAD_EXCEPTIONS = {"Exception", "BaseException"}
_LOG_METHODS = {"error", "warning", "exception", "critical", "debug", "info"}


def is_broad_exception(node: ast.expr) -> bool:
    """Recognize builtin catch-all exception types without resolving imports."""
    if isinstance(node, ast.Tuple):
        return any(is_broad_exception(element) for element in node.elts)
    if isinstance(node, ast.Name):
        return node.id in _BROAD_EXCEPTIONS
    return (
        isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "builtins"
        and node.attr in _BROAD_EXCEPTIONS
    )


def is_logging_call(statement: ast.stmt) -> bool:
    """Recognize direct calls on conventionally named logging receivers."""
    if not isinstance(statement, ast.Expr) or not isinstance(statement.value, ast.Call):
        return False
    function = statement.value.func
    if not isinstance(function, ast.Attribute) or function.attr not in _LOG_METHODS:
        return False
    receiver = function.value
    if isinstance(receiver, ast.Name):
        name = receiver.id
    elif isinstance(receiver, ast.Attribute):
        name = receiver.attr
    else:
        return False
    return name in {"logging", "log", "logger"} or name.endswith("_logger")


def check_exception_handling(file_path: Path) -> list[tuple[int, str, str]]:
    """Return (line, violation type, remediation) for each problematic handler."""
    try:
        content = file_path.read_text(encoding="utf-8")
        tree = ast.parse(content, filename=str(file_path))
    except (SyntaxError, UnicodeDecodeError):
        return []  # Ruff owns syntax and encoding diagnostics.

    exempt_lines = {
        token.start[0]
        for token in tokenize.generate_tokens(io.StringIO(content).readline)
        if token.type == tokenize.COMMENT and _ALLOW.search(token.string)
    }
    violations = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ExceptHandler) or node.lineno in exempt_lines:
            continue
        if node.type is None:
            violations.append(
                (
                    node.lineno,
                    "bare_except",
                    "Bare 'except:' catches process-control exceptions — catch a specific exception type",
                )
            )
        elif is_broad_exception(node.type) and not any(
            isinstance(statement, ast.Raise) or is_logging_call(statement) for statement in node.body
        ):
            violations.append(
                (
                    node.lineno,
                    "broad_exception",
                    "Broad exception handler without logging or re-raising — catch a specific exception, re-raise, or call logger.exception()",
                )
            )
    return sorted(violations)


def main(filenames: list[str]) -> int:
    """Check existing Python files; return 1 when violations are found."""
    failed = False
    for filename in filenames:
        file_path = Path(filename)
        if file_path.suffix != ".py" or not file_path.exists():
            continue
        for line_num, _kind, message in check_exception_handling(file_path):
            print(f"{file_path}:{line_num}: {message}")
            failed = True
    return int(failed)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
