"""Dispatch installed gardener commands without plugin-cache paths."""

from __future__ import annotations

import argparse

import yaml


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="obsidian-knowledge garden")
    parser.add_argument("operation", choices=("audit", "links", "index", "questions", "frontmatter"))
    parser.add_argument("arguments", nargs=argparse.REMAINDER, help=argparse.SUPPRESS)
    return parser


def main(argv: list[str] | None = None) -> int:
    from gardener import audit, frontmatter, index, links, questions

    parser = build_parser()
    args = parser.parse_args(argv)
    commands = {
        "audit": audit.main,
        "links": links.main,
        "index": index.main,
        "questions": questions.main,
        "frontmatter": frontmatter.main,
    }
    try:
        commands[args.operation](args.arguments)
    except (ValueError, OSError, yaml.YAMLError) as exc:
        parser.exit(1, f"Error: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
