"""Bounded subprocess adapter for the official CLI connected to a running Obsidian."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import signal
from pathlib import Path

from lib.vault_index.cli import search_ttl_seconds

# NOTE: docs/MCP.md documents the native bridge configuration and output ceiling.
MAX_NATIVE_OUTPUT_BYTES = 6 * 1024 * 1024


async def read_bounded(stream: asyncio.StreamReader) -> bytes:
    chunks = []
    size = 0
    while chunk := await stream.read(64 * 1024):
        size += len(chunk)
        if size > MAX_NATIVE_OUTPUT_BYTES:
            raise ValueError(f"native Obsidian CLI output exceeds {MAX_NATIVE_OUTPUT_BYTES} bytes")
        chunks.append(chunk)
    return b"".join(chunks)


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
        assert process.stdout is not None and process.stderr is not None
        readers = [
            asyncio.create_task(read_bounded(process.stdout)),
            asyncio.create_task(read_bounded(process.stderr)),
        ]
        waiter = asyncio.create_task(process.wait())
        output = asyncio.gather(*readers, waiter)
        complete = False
        timeout = max(1, search_ttl_seconds())
        try:
            try:
                await asyncio.wait_for(output, timeout=timeout)
                stdout, stderr = (reader.result() for reader in readers)
                returncode = waiter.result()
                complete = True
            except TimeoutError as exc:
                raise ValueError(f"native Obsidian CLI timed out after {timeout} seconds") from exc
        finally:
            if not complete:
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(process.pid, signal.SIGKILL)
                await process.wait()
                for task in [*readers, waiter]:
                    task.cancel()
                await asyncio.gather(*readers, waiter, return_exceptions=True)
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
