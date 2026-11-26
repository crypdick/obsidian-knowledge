"""Bounded subprocess adapter for the official CLI connected to a running Obsidian."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

from lib.vault_index.bounded_process import collect_bounded_output
from lib.vault_index.search_budget import search_ttl_seconds

# NOTE: docs/MCP.md documents the native bridge configuration and output ceiling.
MAX_NATIVE_OUTPUT_BYTES = 6 * 1024 * 1024


class NativeObsidian:
    """Select one configured binary and vault; callers supply only command arguments."""

    def __init__(self, vault_root: Path):
        self.vault_root = vault_root.expanduser().resolve(strict=True)
        if not self.vault_root.is_dir():
            raise ValueError("vault must be a directory")
        self.binary = os.environ.get("OBSIDIAN_KNOWLEDGE_OBSIDIAN_CLI", "obsidian")
        self.vault_name = os.environ.get("OBSIDIAN_KNOWLEDGE_OBSIDIAN_VAULT", self.vault_root.name)
        if not self.binary or not self.vault_name:
            raise ValueError("native Obsidian CLI binary and vault name must not be empty")

    async def _run(self, command: str, *arguments: str) -> str:
        if not command or any(argument.startswith("vault=") for argument in arguments):
            raise ValueError("native Obsidian vault selection is fixed by server configuration")
        try:
            process = await asyncio.create_subprocess_exec(
                self.binary,
                f"vault={self.vault_name}",
                command,
                *arguments,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                start_new_session=True,
            )
        except OSError as exc:
            raise ValueError(
                "cannot execute native Obsidian CLI; set OBSIDIAN_KNOWLEDGE_OBSIDIAN_CLI "
                "to the official CLI binary and connect it to a running app"
            ) from exc
        stdout, stderr, returncode = await collect_bounded_output(
            process,
            label="native Obsidian CLI",
            max_bytes=MAX_NATIVE_OUTPUT_BYTES,
            deadline_seconds=max(1, search_ttl_seconds()),
        )
        text = stdout.decode("utf-8", errors="replace")
        error = stderr.decode("utf-8", errors="replace").strip()
        if returncode:
            raise ValueError(error or text.strip() or f"native Obsidian CLI exited with status {returncode}")
        message = text.strip()
        if message == "Vault not found.":
            raise ValueError(
                "configured native Obsidian vault was not found; check OBSIDIAN_KNOWLEDGE_OBSIDIAN_VAULT"
            )
        if message.startswith(
            ("Error:", "The CLI is unable to find Obsidian.", "Command line interface is not enabled.")
        ):
            raise ValueError(message)
        return text

    async def assert_vault_identity(self) -> None:
        """Check native vault and filesystem root name the same bound directory."""
        reported = (await self._run("vault", "info=path")).strip()
        try:
            matches = await asyncio.to_thread(Path(reported).samefile, self.vault_root)
        except OSError as exc:
            raise ValueError(
                "cannot verify native Obsidian vault identity; mount the vault at its native app path "
                "inside the MCP container"
            ) from exc
        if not matches:
            raise ValueError("native Obsidian vault does not match the configured filesystem vault")

    async def run(self, command: str, *arguments: str) -> str:
        """Verify vault identity, then execute a bounded command without a shell."""
        await self.assert_vault_identity()
        return await self._run(command, *arguments)

    async def run_json(self, command: str, *arguments: str) -> object:
        """Decode native JSON, including eval's prefix and empty search sentinel."""
        output = (await self.run(command, *arguments)).strip()
        if command in {"search", "search:context"} and output == "No matches found.":
            return []
        if command == "properties" and output == "No frontmatter found.":
            return {}
        if command == "eval" and output.startswith("=> "):
            output = output[3:]
        try:
            parsed: object = json.loads(output)
        except json.JSONDecodeError as exc:
            raise ValueError("native Obsidian CLI returned invalid JSON") from exc
        return parsed
