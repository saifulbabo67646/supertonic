"""Local voice builds: a single-slot queue that runs one worker process at a time.

Each job lives in ``data_dir/jobs/<id>/``: ``job.json`` (atomic rewrites), the prepared
``reference.wav``, ``progress.jsonl`` and ``worker.log``. Process handling (spawn, tree
kill) is in :mod:`.process`, running one job in :mod:`.jobrun` and the worker protocol
in :mod:`.worker`.
"""

from __future__ import annotations

import asyncio
import builtins
import contextlib
import logging
import shutil
import sys
import uuid
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Literal

from supertonic_server.builder.audio_prep import prepare_reference
from supertonic_server.builder.jobrun import ActiveRun, RunSpec, execute
from supertonic_server.builder.jobstore import (
    PRUNE_AFTER,
    REFERENCE,
    discard_working_files,
    load_jobs,
    now_iso,
    write_job,
)
from supertonic_server.builder.models import (
    BUILD_METHODS,
    TERMINAL,
    BuildMethod,
    BuildRequest,
    Job,
    JobState,
)
from supertonic_server.builder.process import KILL_WAIT_S, kill_tree
from supertonic_server.core import errors
from supertonic_server.core.scrub import scrub_paths
from supertonic_server.voices.library import VoiceLibrary

logger = logging.getLogger(__name__)

WORKER_MODULE = "supertonic_server.builder.worker"


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
        self._max_waiting = max_waiting
        self._methods: tuple[BuildMethod, ...] = tuple(methods)
        cmd = list(worker_cmd) if worker_cmd else [python, "-m", WORKER_MODULE]
        self._spec = RunSpec(self._root, tuple(cmd), model_dir, timeout_s, library)
        self._jobs: dict[str, Job] = {}
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._preparing = 0
        self._closed = False
        self._current: ActiveRun | None = None
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
            ApiError: 409 ``job_not_running`` for a queued job; 500 ``internal_error`` when
                the stop file cannot be written (the job keeps running and may be asked again).
        """
        job = self.get(job_id)
        if job.state == "queued":
            raise errors.job_not_running(job_id)
        run = self._current
        if run is not None and run.job is job and not run.exited and not job.stopping:
            try:
                (self._root / job_id / "STOP").touch()
            except OSError as exc:
                logger.exception("job %s: could not write the stop file", job_id)
                raise errors.finish_failed(scrub_paths(str(exc))) from None
            job.stopping = True
            try:
                self._persist(job)
            except OSError:  # the worker stops anyway; the in-memory job is authoritative
                logger.exception("job %s: could not save its stopping flag", job_id)
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
            run = ActiveRun(job)
            self._current = run
            try:
                await execute(run, self._spec, self._persist, self._settle)
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
