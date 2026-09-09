#!/usr/bin/env python3
"""Prepare a synchronized patch release, preserving explicit version bumps."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import tomllib
import urllib.request
from pathlib import Path


def release_state(root: Path, source: str) -> str:
    """Reuse this push's release commit; ignore CI overtaken by another push."""
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    if head == source:
        return "new"
    parent = subprocess.check_output(["git", "rev-parse", "HEAD^"], cwd=root, text=True).strip()
    message = subprocess.check_output(["git", "log", "-1", "--format=%B"], cwd=root, text=True)
    if (
        parent == source
        and message.startswith("Release ")
        and f"Source-Commit: {source}" in message.splitlines()
    ):
        return "retry"
    return "stale"


def prepare_version(root: Path, published: list[str]) -> str:
    """Keep a new manual version, otherwise increment the latest patch."""
    project_path = root / "pyproject.toml"
    project = project_path.read_text()
    current = tomllib.loads(project)["project"]["version"]
    if not re.fullmatch(r"\d+\.\d+\.\d+", current):
        raise ValueError(f"Release version must be major.minor.patch: {current}")
    current_parts = tuple(map(int, current.split(".")))
    released = [
        tuple(map(int, value.split("."))) for value in published if re.fullmatch(r"\d+\.\d+\.\d+", value)
    ]
    latest = max(released, default=(-1, -1, -1))
    version = current if current_parts > latest else f"{latest[0]}.{latest[1]}.{latest[2] + 1}"
    project_path.write_text(
        re.sub(r'^version = "[^"]+"$', f'version = "{version}"', project, count=1, flags=re.M)
    )

    for name in (
        ".codex-plugin/plugin.json",
        ".claude-plugin/plugin.json",
        ".claude-plugin/marketplace.json",
    ):
        path = root / name
        data = json.loads(path.read_text())
        if name.endswith("marketplace.json"):
            plugin = next(item for item in data["plugins"] if item["name"] == "obsidian-knowledge")
            plugin["version"] = version
        else:
            data["version"] = version
        path.write_text(json.dumps(data, indent=2) + "\n")
    hermes = root / "plugin.yaml"
    hermes.write_text(
        re.sub(r"^version: .+$", f"version: {version}", hermes.read_text(), count=1, flags=re.M)
    )
    return version


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"[0-9a-f]{40}", args.source):
        parser.error("source must be a full Git commit SHA")
    root = Path.cwd()
    state = release_state(root, args.source)
    version = tomllib.loads((root / "pyproject.toml").read_text())["project"]["version"]
    if state == "new":
        with urllib.request.urlopen("https://pypi.org/pypi/obsidian-knowledge/json", timeout=30) as response:
            published = list(json.load(response)["releases"])
        version = prepare_version(root, published)
    with Path(os.environ["GITHUB_OUTPUT"]).open("a") as output:
        output.write(f"state={state}\nversion={version}\n")


if __name__ == "__main__":
    main()
