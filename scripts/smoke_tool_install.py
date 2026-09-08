#!/usr/bin/env python3
"""Install a built wheel with plain uv tool install, then exercise first setup.

Runs outside the checkout, with isolated tool, registry, and cache directories.
No Ollama, Claude, existing vault, or development dependencies are needed.
Usage: python scripts/smoke_tool_install.py dist/obsidian_knowledge-*.whl
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import tempfile
from pathlib import Path


def run(args: list[str], env: dict[str, str], cwd: Path) -> str:
    result = subprocess.run(args, env=env, cwd=cwd, capture_output=True, text=True, timeout=120)
    output = result.stdout + result.stderr
    print(output, end="")
    if result.returncode:
        raise RuntimeError(f"Command failed ({result.returncode}): {args}")
    if "Give Feedback / Get Help" in output or "LiteLLM.Info" in output:
        raise RuntimeError("Offline indexing attempted an embedding request")
    return output


def main() -> None:
    wheel = Path(sys.argv[1]).resolve(strict=True)
    uv = shutil.which("uv")
    if uv is None:
        raise RuntimeError("uv must be on PATH")
    with tempfile.TemporaryDirectory(prefix="obsidian-install-") as directory:
        root = Path(directory)
        env = {
            key: value
            for key, value in os.environ.items()
            if key not in {"PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV", "UV_PYTHON"}
        }
        env.update({"UV_TOOL_DIR": str(root / "tools"), "UV_TOOL_BIN_DIR": str(root / "bin")})
        run([uv, "tool", "install", "--no-config", str(wheel)], env, root)
        python = root / "tools" / "obsidian-knowledge" / "bin" / "python"
        run([uv, "pip", "check", "--python", str(python)], env, root)
        run([str(python), "-c", "import sys; print(sys.version)"], env, root)

        vault = root / "vault"
        vault.mkdir()
        (vault / "example.md").write_text("# Install check\nQuokkas are marsupials.\n")
        env.update({
            "PATH": str(root / "bin"),  # Keep Claude plugin installation out of this check.
            "OBSIDIAN_KNOWLEDGE_VAULTS_CONFIG": str(root / "config" / "vaults.yaml"),
            "OBSIDIAN_KNOWLEDGE_CACHE_ROOT": str(root / "cache"),
            "MEMWEAVE_EMBEDDING_MODEL": "ollama/bge-m3",
        })
        cli = str(root / "bin" / "obsidian-knowledge")
        # Reserve a local port without listening so the probe deterministically fails.
        with socket.socket() as unavailable:
            unavailable.bind(("127.0.0.1", 0))
            env["MEMWEAVE_EMBEDDING_API_BASE"] = f"http://127.0.0.1:{unavailable.getsockname()[1]}"
            output = run([cli, "setup", "--vault", str(vault)], env, root)
            if "Setup complete." not in output or "Search mode: keyword-only" not in output:
                raise RuntimeError("First-time setup did not finish in keyword mode")
            # Omit --vault to check that setup registered it in the isolated config.
            output = run([cli, "search", "Quokkas"], env, root)
            if "example.md" not in output:
                raise RuntimeError("Installed CLI failed to retrieve the indexed note")
        print("Clean tool install, setup, and search passed without Ollama.")


if __name__ == "__main__":
    main()
