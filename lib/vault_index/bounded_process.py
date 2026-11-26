"""Read bounded subprocess output and reap its process group on failure."""

from __future__ import annotations

import asyncio
import contextlib
import os
import signal


async def _read_bounded(stream: asyncio.StreamReader, label: str, max_bytes: int) -> bytes:
    chunks = []
    size = 0
    while chunk := await stream.read(64 * 1024):
        size += len(chunk)
        if size > max_bytes:
            raise ValueError(f"{label} output exceeds {max_bytes} bytes")
        chunks.append(chunk)
    return b"".join(chunks)


async def collect_bounded_output(
    process: asyncio.subprocess.Process, *, label: str, max_bytes: int, deadline_seconds: int
) -> tuple[bytes, bytes, int]:
    """Collect stdout/stderr from a subprocess started in its own session."""
    assert process.stdout is not None and process.stderr is not None
    readers = [
        asyncio.create_task(_read_bounded(process.stdout, label, max_bytes)),
        asyncio.create_task(_read_bounded(process.stderr, label, max_bytes)),
    ]
    waiter = asyncio.create_task(process.wait())
    output = asyncio.gather(*readers, waiter)
    complete = False
    try:
        try:
            await asyncio.wait_for(output, timeout=deadline_seconds)
            stdout, stderr = (reader.result() for reader in readers)
            returncode = waiter.result()
            complete = True
        except TimeoutError as exc:
            raise ValueError(f"{label} timed out after {deadline_seconds} seconds") from exc
    finally:
        if not complete:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)
            for task in [*readers, waiter]:
                task.cancel()
            await asyncio.gather(*readers, waiter, return_exceptions=True)
            # A capped reader can leave its pipe paused; wait() alone then deadlocks.
            await process.communicate()
    return stdout, stderr, returncode
