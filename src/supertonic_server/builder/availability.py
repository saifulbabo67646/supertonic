"""Can this machine build voices? Asks the worker's ``--self-test`` in a child process.

The server never imports torch itself; the probe runs ``python -m
supertonic_server.builder.worker --self-test`` and parses its single JSON line.
"""

from __future__ import annotations

import contextlib
import functools
import json
import logging
import os
import subprocess
import sys
from dataclasses import dataclass
from typing import Any

from supertonic_server.builder.models import BUILD_METHODS, BuildMethod
from supertonic_server.builder.process import KILL_WAIT_S, group_kwargs, kill_tree_sync

logger = logging.getLogger(__name__)

WORKER_MODULE = "supertonic_server.builder.worker"


@dataclass(frozen=True)
class ProbeResult:
    """Outcome of the local builder probe.

    Attributes:
        available: Torch imports and CUDA is usable.
        reason: ``"ok"``, or why building is unavailable.
        device: GPU name, if any.
        vram_mb: GPU memory in MiB, if known.
        methods: Build methods whose dependencies import.
    """

    available: bool
    reason: str
    device: str | None
    vram_mb: int | None
    methods: tuple[BuildMethod, ...]


def _self_test_cmd(python: str) -> list[str]:
    return [python, "-m", WORKER_MODULE, "--self-test"]


def _unavailable(reason: str) -> ProbeResult:
    return ProbeResult(False, reason, None, None, ())


def _parse(stdout: str) -> ProbeResult:
    """Read the last JSON object line of the self-test output."""
    line: dict[str, Any] | None = None
    for raw in reversed(stdout.splitlines()):
        try:
            obj = json.loads(raw)
        except ValueError:
            continue
        if isinstance(obj, dict):
            line = obj
            break
    if line is None:
        return _unavailable("unreadable self-test output")
    if line.get("type") == "error":
        return _unavailable(f"{line.get('code', 'error')}: {line.get('message', '')}")
    if line.get("type") != "probe":
        return _unavailable("unreadable self-test output")
    methods = tuple(m for m in BUILD_METHODS if m in (line.get("methods") or []))
    vram = line.get("vram_mb")
    device = line.get("device")
    result = ProbeResult(
        available=bool(line.get("torch")) and line.get("cuda") is True,
        reason="ok",
        device=str(device) if device is not None else None,
        vram_mb=int(vram) if isinstance(vram, int | float) else None,
        methods=methods,
    )
    if not result.available:
        return ProbeResult(False, "CUDA is unavailable", None, None, methods)
    return result


@functools.cache
def detect_local_builder(python: str = sys.executable, timeout_s: float = 60) -> ProbeResult:
    """Probe the local builder once per process (``detect_local_builder.cache_clear()`` resets).

    Blocking (it waits for a child interpreter, up to ``timeout_s`` plus a few seconds): call
    it from async code via ``asyncio.to_thread``. The self-test runs in its own process
    group, and the whole group is killed on timeout, so a descendant holding the pipes cannot
    keep the probe waiting.

    Args:
        python: Interpreter that has (or lacks) the ``builder`` extra.
        timeout_s: Give up on the self-test after this many seconds.
    """
    env = {**os.environ, "PYTHONUTF8": "1"}
    try:
        proc = subprocess.Popen(
            _self_test_cmd(python),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            **group_kwargs(),
        )
    except OSError as exc:
        result = _unavailable(f"builder self-test could not start: {exc}")
    else:
        try:
            stdout, _ = proc.communicate(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            kill_tree_sync(proc.pid)
            try:
                proc.communicate(timeout=KILL_WAIT_S)
            except subprocess.TimeoutExpired:  # a straggler outside the tree holds the pipes
                proc.kill()
                for pipe in (proc.stdout, proc.stderr):
                    if pipe is not None:
                        with contextlib.suppress(OSError):
                            pipe.close()
                proc.wait()
            result = _unavailable(f"builder self-test timed out after {timeout_s:g} s")
        else:
            result = _parse(stdout)
    logger.info("local voice builder: %s", result)
    return result
