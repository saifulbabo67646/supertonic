"""Local voice builds: a single-slot queue that runs one worker process at a time.

Each job lives in ``data_dir/jobs/<id>/``: ``job.json`` (atomic rewrites), the prepared
``reference.wav``, ``progress.jsonl`` and ``worker.log``. Process handling (spawn, tree
kill) is in :mod:`.process`; the worker protocol in :mod:`.worker`.
"""

from __future__ import annotations

import asyncio
import builtins
import contextlib
import logging
import os
import shutil
import sys
import time
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import Any, Literal

from supertonic_server.builder.audio_prep import prepare_reference
from supertonic_server.builder.jobstore import (
    REFERENCE,
    discard_working_files,
    load_jobs,
    now_iso,
    read_style,
    write_job,
)
from supertonic_server.builder.models import BUILD_METHODS, BuildMethod, BuildRequest, Job, JobState
from supertonic_server.builder.process import KILL_WAIT_S, kill_tree, spawn
from supertonic_server.builder.runlog import RunLog
from supertonic_server.core import errors
from supertonic_server.core.errors import ApiError
from supertonic_server.core.scrub import scrub_paths
from supertonic_server.voices.library import VoiceLibrary

logger = logging.getLogger(__name__)

WORKER_MODULE = "supertonic_server.builder.worker"
PRUNE_AFTER = timedelta(days=7)
TERMINAL = frozenset({"succeeded", "failed", "cancelled"})


@dataclass
class _Run:
    """The job currently held by the single worker slot."""

    job: Job
    proc: asyncio.subprocess.Process | None = None
    cancelled: bool = False
    exited: bool = False
    """The worker is gone (the result is being imported)."""
    finished: asyncio.Event = field(default_factory=asyncio.Event)


class JobManager:
    """Queue voice builds and run them one at a time in a worker subprocess.

    Args:
        data_dir: Server data directory; jobs live in ``data_dir/jobs``.
        library: Where finished voices are imported.
        model_dir: Supertonic 3 model directory handed to the worker.
        python: Interpreter that runs the worker.
        timeout_s: Wall-clock limit per build; then the job fails with ``timeout``.
        max_waiting: Queued (not running) jobs allowed before ``builder_busy``.
        methods: Build methods this machine can run.
        worker_cmd: Command replacing ``python -m supertonic_server.builder.worker`` (tests).
        device: GPU name reported by health (``None`` when unknown).
        vram_mb: GPU memory reported by health (``None`` when unknown).
    """

    kind: Literal["local"] = "local"

    def __init__(
        self,
        data_dir: Path,
        library: VoiceLibrary,
        model_dir: Path,
        *,
        python: str = sys.executable,
        timeout_s: float,
        max_waiting: int = 8,
        methods: Sequence[BuildMethod] = BUILD_METHODS,
        worker_cmd: Sequence[str] | None = None,
        device: str | None = None,
        vram_mb: int | None = None,
    ) -> None:
        self._device, self._vram_mb = device, vram_mb
        self._root = data_dir / "jobs"
        self._library = library
        self._model_dir = model_dir
        self._timeout_s = timeout_s
        self._max_waiting = max_waiting
        self._methods: tuple[BuildMethod, ...] = tuple(methods)
        self._cmd = list(worker_cmd) if worker_cmd else [python, "-m", WORKER_MODULE]
        self._jobs: dict[str, Job] = {}
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._preparing = 0
        self._closed = False
        self._current: _Run | None = None
        self._runner: asyncio.Task[None] | None = None

    @property
    def methods(self) -> tuple[BuildMethod, ...]:
        """Build methods this builder can run."""
        return self._methods

    def detail(self) -> dict[str, Any]:
        """Health detail: ``{"device", "vram_mb", "methods"}``."""
        return {"device": self._device, "vram_mb": self._vram_mb, "methods": list(self._methods)}

    async def start(self) -> None:
        """Load jobs from disk (interrupted ones fail, old ones are pruned); start the runner."""
        self._root.mkdir(parents=True, exist_ok=True)
        self._closed = False
        for job in load_jobs(self._root, PRUNE_AFTER):
            self._jobs[job.id] = job
            if job.state not in TERMINAL:
                self._settle(job, "failed", {"code": "interrupted", "message": "server restarted"})
        self._runner = asyncio.create_task(self._run_forever(), name="voice-builder")

    async def close(self) -> None:
        """Refuse new builds, cancel the running job and stop the runner.

        Queued jobs stay queued on disk (the next ``start`` marks them ``interrupted``).
        """
        self._closed = True
        if self._current is not None:
            await self.cancel(self._current.job.id)
        if self._runner is not None:
            self._runner.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._runner
            self._runner = None

    async def submit(
        self, req: BuildRequest, files: Sequence[tuple[str, bytes]], builder_label: str = "local"
    ) -> Job:
        """Validate, prepare the reference audio and queue a build.

        Raises:
            ApiError: 400 for a bad request, audio or ``method_unavailable``; 503
                ``builder_busy`` when ``max_waiting`` jobs are already waiting, or
                ``builder_unavailable`` once the manager is closing.
        """
        self._check_open()
        req.validate()
        if req.method not in self._methods:
            raise errors.method_unavailable(req.method, self._methods)
        waiting = sum(j.state == "queued" for j in self._jobs.values()) + self._preparing
        if waiting >= self._max_waiting:
            raise errors.builder_busy()
        job_id = uuid.uuid4().hex
        folder = self._root / job_id
        self._preparing += 1
        try:
            folder.mkdir(parents=True)
            await asyncio.to_thread(prepare_reference, files, folder / REFERENCE)
        except BaseException:
            shutil.rmtree(folder, ignore_errors=True)
            raise
        finally:
            self._preparing -= 1
        if self._closed:  # closed while the audio was being prepared
            shutil.rmtree(folder, ignore_errors=True)
            self._check_open()
        job = Job(job_id, "queued", req, now_iso(), None, None, None, None, None, builder_label)
        self._jobs[job_id] = job
        self._persist(job)
        self._queue.put_nowait(job_id)
        return job

    def _check_open(self) -> None:
        if self._closed:
            raise errors.builder_unavailable("Voice builder is shutting down")

    def get(self, job_id: str) -> Job:
        """Return a job or raise 404 ``job_not_found``."""
        job = self._jobs.get(job_id)
        if job is None:
            raise errors.job_not_found(job_id)
        return job

    def list(self, limit: int = 50) -> builtins.list[Job]:
        """Most recent jobs first."""
        return sorted(self._jobs.values(), key=lambda j: j.created_at, reverse=True)[:limit]

    async def cancel(self, job_id: str) -> Job:
        """Cancel a queued or running job (killing its worker); finished jobs are unchanged."""
        job = self.get(job_id)
        run = self._current
        if job.state == "queued":
            self._settle(job, "cancelled", None)
        elif job.state == "running" and run is not None and run.job is job:
            run.cancelled = True
            if run.proc is not None:
                await kill_tree(run.proc)
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(run.finished.wait(), KILL_WAIT_S * 2)
        return job

    async def finish(self, job_id: str) -> Job:
        """Ask the running worker to end the timbre stage now (rhythm matching still runs).

        Accepted once: while the job is already stopping, or once it has ended, the job is
        returned unchanged.

        Raises:
            ApiError: 409 ``job_not_running`` for a queued job.
        """
        job = self.get(job_id)
        if job.state == "queued":
            raise errors.job_not_running(job_id)
        run = self._current
        if run is not None and run.job is job and not run.exited and not job.stopping:
            (self._root / job_id / "STOP").touch()
            job.stopping = True
            self._persist(job)
        return job

    # -- internals ---------------------------------------------------------------------

    def _persist(self, job: Job) -> None:
        write_job(self._root / job.id, job)

    def _settle(self, job: Job, state: JobState, error: dict[str, Any] | None) -> None:
        """Move ``job`` to a terminal state, drop its working files and persist.

        Never raises for file errors: the in-memory job is authoritative, and a working file
        that cannot be removed must not keep the terminal state off disk.
        """
        job.state = state
        job.error = error
        job.finished_at = now_iso()
        discard_working_files(self._root / job.id)
        try:
            self._persist(job)
        except OSError:
            logger.exception("job %s: could not save its %s state", job.id, state)

    async def _run_forever(self) -> None:
        while True:
            job_id = await self._queue.get()
            job = self._jobs.get(job_id)
            if job is None or job.state != "queued":
                continue
            run = _Run(job)
            self._current = run
            try:
                await self._run(run)
            except Exception as exc:  # never let one job stop the runner
                logger.exception("voice build %s crashed the runner", job_id)
                if job.state not in TERMINAL:
                    self._settle(
                        job, "failed", {"code": "internal_error", "message": scrub_paths(str(exc))}
                    )
            finally:
                if job.state not in TERMINAL:  # the runner itself was cancelled (close)
                    self._settle(job, "cancelled", None)
                self._current = None
                run.finished.set()

    async def _run(self, run: _Run) -> None:
        job = run.job
        folder = self._root / job.id
        job.state, job.started_at = "running", now_iso()
        self._persist(job)
        cmd = [
            *self._cmd,
            "--method", job.request.method,
            "--wav", str(folder / REFERENCE),
            "--out", str(folder / "style.json"),
            "--report", str(folder / "report.json"),
            "--model-dir", str(self._model_dir),
            "--stop-file", str(folder / "STOP"),
        ]  # fmt: skip
        started = time.monotonic()
        with RunLog(folder, job, lambda: self._persist(job)) as log:
            try:
                proc = await spawn(cmd, {**os.environ, "PYTHONUTF8": "1"})
            except OSError as exc:
                self._settle(
                    job, "failed", {"code": "worker_failed", "message": scrub_paths(str(exc))}
                )
                return
            run.proc = proc
            if run.cancelled:
                await kill_tree(proc)
            timed_out = await log.follow(proc, self._timeout_s)
        run.exited = True
        seconds = round(time.monotonic() - started, 1)
        if run.cancelled:
            self._settle(job, "cancelled", None)
        elif timed_out:
            limit = f"{self._timeout_s / 60:g} min"
            self._settle(job, "failed", {"code": "timeout", "message": f"build exceeded {limit}"})
        elif log.report is not None and proc.returncode == 0:
            importing = asyncio.ensure_future(self._import(job, log.report, seconds))
            try:
                await asyncio.shield(importing)
            except asyncio.CancelledError:  # close(): finish the import, never half-record it
                await importing
                raise
        else:
            self._settle(job, "failed", log.failure(proc.returncode))

    async def _import(self, job: Job, report: dict[str, Any], seconds: float) -> None:
        req = job.request
        try:
            style = read_style(self._root / job.id)
            extra = {**report, "builder": job.builder, "seconds": seconds}
            voice = await asyncio.to_thread(
                self._library.import_style,
                style,
                req.name.strip(),
                req.description,
                req.tags,
                req.source_note,
                extra=extra,
            )
        except (OSError, ValueError, ApiError) as exc:
            message = scrub_paths(exc.message if isinstance(exc, ApiError) else str(exc))
            self._settle(job, "failed", {"code": "import_failed", "message": message})
            return
        job.voice_id = voice.id
        self._settle(job, "succeeded", None)
