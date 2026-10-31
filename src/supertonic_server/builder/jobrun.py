"""Run one queued voice build in a worker process and import its result.

:class:`~supertonic_server.builder.jobs.JobManager` owns the queue and the single worker
slot; this module owns what happens inside the slot: spawn the worker, follow its output
until it exits or times out, then settle the job or import the finished voice.
"""

from __future__ import annotations

import asyncio
import os
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from supertonic_server.builder.jobstore import REFERENCE, now_iso, read_style
from supertonic_server.builder.models import Job, JobState
from supertonic_server.builder.process import kill_tree, spawn
from supertonic_server.builder.runlog import RunLog
from supertonic_server.core.errors import ApiError
from supertonic_server.core.scrub import scrub_paths
from supertonic_server.voices.library import VoiceLibrary

__all__ = ["ActiveRun", "RunSpec", "execute"]

Persist = Callable[[Job], None]
Settle = Callable[[Job, JobState, dict[str, Any] | None], None]


@dataclass
class ActiveRun:
    """The job currently held by the single worker slot."""

    job: Job
    proc: asyncio.subprocess.Process | None = None
    cancelled: bool = False
    exited: bool = False
    """The worker is gone (the result is being imported)."""
    finished: asyncio.Event = field(default_factory=asyncio.Event)


@dataclass(frozen=True)
class RunSpec:
    """What every run needs from its manager."""

    root: Path
    """The jobs directory; a job's files are in ``root/<id>/``."""
    cmd: Sequence[str]
    """The worker command, without per-job arguments."""
    model_dir: Path
    timeout_s: float
    library: VoiceLibrary


async def execute(run: ActiveRun, spec: RunSpec, persist: Persist, settle: Settle) -> None:
    """Run ``run.job`` to a terminal state (or leave it running if this task is cancelled).

    Args:
        run: The slot's run; ``proc`` and ``exited`` are updated here, ``cancelled`` is
            read (the manager sets it from :meth:`JobManager.cancel`).
        spec: Paths, command, limits and the library finished voices go to.
        persist: Save the job record.
        settle: Move the job to a terminal state.
    """
    job = run.job
    folder = spec.root / job.id
    job.state, job.started_at = "running", now_iso()
    persist(job)
    cmd = [
        *spec.cmd,
        "--method", job.request.method,
        "--wav", str(folder / REFERENCE),
        "--out", str(folder / "style.json"),
        "--report", str(folder / "report.json"),
        "--model-dir", str(spec.model_dir),
        "--stop-file", str(folder / "STOP"),
    ]  # fmt: skip
    started = time.monotonic()
    with RunLog(folder, job, lambda: persist(job)) as log:
        try:
            proc = await spawn(cmd, {**os.environ, "PYTHONUTF8": "1"})
        except OSError as exc:
            settle(job, "failed", {"code": "worker_failed", "message": scrub_paths(str(exc))})
            return
        run.proc = proc
        if run.cancelled:
            await kill_tree(proc)
        timed_out = await log.follow(proc, spec.timeout_s)
    run.exited = True
    seconds = round(time.monotonic() - started, 1)
    if run.cancelled:
        settle(job, "cancelled", None)
    elif timed_out:
        limit = f"{spec.timeout_s / 60:g} min"
        settle(job, "failed", {"code": "timeout", "message": f"build exceeded {limit}"})
    elif log.report is not None and proc.returncode == 0:
        importing = asyncio.ensure_future(_import(job, log.report, seconds, spec, settle))
        try:
            await asyncio.shield(importing)
        except asyncio.CancelledError:  # close(): finish the import, never half-record it
            await importing
            raise
    else:
        settle(job, "failed", log.failure(proc.returncode))


async def _import(
    job: Job, report: dict[str, Any], seconds: float, spec: RunSpec, settle: Settle
) -> None:
    req = job.request
    try:
        style = read_style(spec.root / job.id)
        extra = {**report, "builder": job.builder, "seconds": seconds}
        voice = await asyncio.to_thread(
            spec.library.import_style,
            style,
            req.name.strip(),
            req.description,
            req.tags,
            req.source_note,
            extra=extra,
        )
    except (OSError, ValueError, ApiError) as exc:
        message = scrub_paths(exc.message if isinstance(exc, ApiError) else str(exc))
        settle(job, "failed", {"code": "import_failed", "message": message})
        return
    job.voice_id = voice.id
    settle(job, "succeeded", None)
