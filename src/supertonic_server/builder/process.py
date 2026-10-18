"""Start a worker in its own process group and kill the whole tree (Windows and POSIX)."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import signal
import subprocess
import sys
from collections.abc import Mapping, Sequence
from typing import Any

logger = logging.getLogger(__name__)

KILL_WAIT_S = 5.0
STREAM_LIMIT = 4 * 1024 * 1024
"""Longest stdout/stderr line read in one piece."""


def group_kwargs() -> dict[str, Any]:
    """Keyword arguments that put the child in a new process group."""
    if sys.platform == "win32":
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


async def spawn(cmd: Sequence[str], env: Mapping[str, str]) -> asyncio.subprocess.Process:
    """Start ``cmd`` with piped stdout/stderr, no stdin, in its own process group.

    Raises:
        OSError: when the program cannot be started.
    """
    return await asyncio.create_subprocess_exec(
        *cmd,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=dict(env),
        limit=STREAM_LIMIT,
        **group_kwargs(),
    )


async def kill_tree(proc: asyncio.subprocess.Process) -> None:
    """Kill ``proc`` and its descendants; a no-op once ``proc`` has been reaped.

    The process is never reaped here, so its id (and on POSIX its process group id) cannot
    be reused while this runs.
    """
    if proc.returncode is not None:
        return
    if sys.platform == "win32":
        try:
            killer = await asyncio.create_subprocess_exec(
                "taskkill", "/T", "/F", "/PID", str(proc.pid),
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )  # fmt: skip
            await asyncio.wait_for(killer.wait(), KILL_WAIT_S)
        except (OSError, TimeoutError) as exc:
            logger.warning("taskkill failed for pid %s: %s", proc.pid, exc)
    else:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        except OSError as exc:
            logger.warning("killpg failed for pid %s: %s", proc.pid, exc)
    with contextlib.suppress(ProcessLookupError):
        proc.kill()  # the leader at least, whatever happened above


async def kill_group_stragglers(proc: asyncio.subprocess.Process) -> None:
    """After the leader exited, kill what is left of its POSIX process group.

    Only call this while a straggler is known to exist (it still holds the leader's pipes),
    which keeps the group id from being reused. Windows cannot walk the tree of an exited
    parent; the caller just stops reading there.
    """
    if sys.platform != "win32":
        with contextlib.suppress(OSError):
            os.killpg(proc.pid, signal.SIGKILL)


def kill_tree_sync(pid: int) -> None:
    """Blocking :func:`kill_tree` for a ``subprocess.Popen`` child that has not been reaped."""
    if sys.platform == "win32":
        cmd = ["taskkill", "/T", "/F", "/PID", str(pid)]
        try:
            subprocess.run(cmd, capture_output=True, timeout=KILL_WAIT_S, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            logger.warning("taskkill failed for pid %s: %s", pid, exc)
    else:
        with contextlib.suppress(OSError):
            os.killpg(pid, signal.SIGKILL)
