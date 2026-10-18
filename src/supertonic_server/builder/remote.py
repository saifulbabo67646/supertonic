"""Forward voice builds to a remote builder and import the finished voices locally.

A machine without a GPU sets ``SUPERTONIC_BUILDER_URL`` to another Supertonic server that
has a local builder. :class:`RemoteBuilder` validates the request, checks that server's
health, forwards the build, keeps a local mirror job (``data_dir/jobs/<id>/job.json`` with
``remote_id``) and polls the remote job; on success the voice is imported locally with
``builder: "remote:<host>"`` (see :mod:`.remote_import`).

If polling keeps failing for ``lost_after_s`` the job fails ``builder_lost`` and nothing is
imported. After a restart, mirror jobs still queued or running resume polling.
"""

from __future__ import annotations

import asyncio
import builtins
import contextlib
import logging
import uuid
from collections.abc import Sequence
from datetime import timedelta
from pathlib import Path
from typing import Any, Literal

import httpx

from supertonic_server.builder.jobstore import load_jobs, now_iso, write_job
from supertonic_server.builder.models import BUILD_METHODS, BuildMethod, BuildRequest, Job, JobState
from supertonic_server.builder.remote_http import DEFAULT_TIMEOUT, BuilderClient, Unreachable
from supertonic_server.builder.remote_poll import POLL_ERRORS, TERMINAL, RemotePolling
from supertonic_server.core import errors
from supertonic_server.core.errors import ApiError
from supertonic_server.voices import VoiceLibrary

logger = logging.getLogger(__name__)

PRUNE_AFTER = timedelta(days=7)


class RemoteBuilder(RemotePolling):
    """A :class:`~.models.Builder` that runs builds on another Supertonic server.

    Args:
        base_url: The builder's root URL, e.g. ``http://win-laptop:8787``.
        api_key: The builder's API key, sent as ``Authorization: Bearer``.
        library: Where finished voices are imported.
        data_dir: Server data directory; mirror jobs live in ``data_dir/jobs``.
        http: Client to use (tests); by default one is created and closed with the builder.
        poll_s: Seconds between polls of each active remote job.
        lost_after_s: How long polling may keep failing before the job fails ``builder_lost``.
    """

    kind: Literal["remote"] = "remote"

    def __init__(
        self,
        base_url: str,
        api_key: str | None,
        library: VoiceLibrary,
        data_dir: Path,
        *,
        http: httpx.AsyncClient | None = None,
        poll_s: float = 3.0,
        lost_after_s: float = 120.0,
    ) -> None:
        self._owns_http = http is None
        self._http = http if http is not None else httpx.AsyncClient(timeout=DEFAULT_TIMEOUT)
        self._client = BuilderClient(base_url, api_key, self._http)
        self.host = self._client.host
        self.label = f"remote:{self.host}"
        self._library = library
        self._root = data_dir / "jobs"
        self._poll_s, self._lost_after_s = poll_s, lost_after_s
        self._methods: tuple[BuildMethod, ...] = BUILD_METHODS
        self._jobs: dict[str, Job] = {}
        self._pollers: dict[str, asyncio.Task[None]] = {}
        self._importing: set[str] = set()
        self._refresh: asyncio.Task[None] | None = None
        self._closed = False

    @property
    def methods(self) -> tuple[BuildMethod, ...]:
        """Methods the remote reported at its last health check (all, before any contact)."""
        return self._methods

    def detail(self) -> dict[str, Any]:
        """Health detail: ``{"host": "<host:port>", "methods": [...]}``."""
        return {"host": self.host, "methods": list(self._methods)}

    async def start(self) -> None:
        """Load mirror jobs (resuming active ones); fetch the remote's methods in the background.

        Never fails because the remote is down: reachability is checked at submit time.
        Calling it again while started does nothing.
        """
        if self._refresh is not None:
            return
        self._root.mkdir(parents=True, exist_ok=True)
        self._closed = False
        for job in load_jobs(self._root, PRUNE_AFTER):
            self._jobs[job.id] = job
            if job.state in TERMINAL:
                continue
            if job.remote_id is None:  # left by a local builder that no longer runs here
                self._settle(job, "failed", {"code": "interrupted", "message": "server restarted"})
            else:
                self._follow(job)
        self._refresh = asyncio.create_task(self._refresh_methods(), name="builder-methods")

    async def close(self) -> None:
        """Stop polling (remote jobs keep running; the next ``start`` resumes them)."""
        self._closed = True
        tasks = [*self._pollers.values(), *([self._refresh] if self._refresh else [])]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self._pollers.clear()
        self._refresh = None
        if self._owns_http:
            await self._http.aclose()

    async def submit(
        self, req: BuildRequest, files: Sequence[tuple[str, bytes]], builder_label: str = "local"
    ) -> Job:
        """Validate the request, then forward it to the remote and start following it.

        The remote checks the audio and the method (``invalid_reference_audio`` and
        ``method_unavailable`` come back unchanged). ``builder_label`` is ignored: forwarded
        jobs are always ``remote:<host>``.

        Raises:
            ApiError: 400 for a bad request (before any contact); 503 ``builder_unavailable``
                when the remote is unreachable or has no local builder; else the remote's.
        """
        if self._closed:
            raise errors.builder_unavailable("Voice builder is shutting down")
        req.validate()
        await self._check_health()
        try:
            remote = Job.from_dict(await self._client.submit(req, files))
        except Unreachable as exc:
            raise self._client.unreachable(str(exc)) from exc
        except (ValueError, KeyError, TypeError) as exc:
            raise self._client.unreachable(f"unexpected job from the builder: {exc}") from exc
        job = Job(
            uuid.uuid4().hex, remote.state, req, now_iso(), remote.started_at, None,
            remote.progress, None, None, self.label, remote.stopping, remote_id=remote.id,
        )  # fmt: skip
        (self._root / job.id).mkdir(parents=True)
        self._jobs[job.id] = job
        write_job(self._root / job.id, job)
        self._follow(job)
        return job

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
        """Cancel the remote job, then mark the mirror ``cancelled``; finished jobs are unchanged.

        An unreachable remote still cancels locally (nothing will be imported). A job whose
        remote finished first, or whose result is being imported, settles as usual.
        """
        job = self.get(job_id)
        if job.state in TERMINAL or job.remote_id is None:
            return job
        poller = self._pollers.get(job_id)
        if poller is not None:
            if job_id in self._importing:
                await asyncio.gather(poller, return_exceptions=True)
                return job
            poller.cancel()
            await asyncio.gather(poller, return_exceptions=True)
        if job.state in TERMINAL:
            return job
        try:
            remote = Job.from_dict(await self._client.cancel(job.remote_id))
        except POLL_ERRORS as exc:
            logger.warning("job %s: could not cancel it on %s: %s", job.id, self.host, exc)
            remote = None
        if job.state in TERMINAL:  # settled while the DELETE was in flight
            return job
        if remote is not None and remote.state in ("succeeded", "failed"):
            self._follow(job, immediate=True)  # it finished first: settle as usual
            return job
        if job_id in self._pollers:  # a concurrent cancel restarted the poller
            return job
        self._settle(job, "cancelled", None)
        return job

    async def finish(self, job_id: str) -> Job:
        """Ask the remote job to save its best result now.

        Raises:
            ApiError: 409 ``job_not_running`` for a queued job; 503 ``builder_unavailable``
                when the remote cannot be reached; other remote errors name the local job.
        """
        job = self.get(job_id)
        if job.state in TERMINAL or job.remote_id is None:
            return job
        try:
            remote = Job.from_dict(await self._client.finish(job.remote_id))
        except Unreachable as exc:
            raise self._client.unreachable(str(exc)) from exc
        except ApiError as exc:
            message = exc.message.replace(job.remote_id, job.id)
            raise ApiError(exc.status, exc.code, message, exc.param, exc.type) from exc
        if remote.stopping and not job.stopping:
            job.stopping = True
            self._save(job)
        return job

    # -- internals ---------------------------------------------------------------------

    async def _check_health(self) -> None:
        """Require the remote to report a local builder; refresh ``methods``."""
        methods = await self._client.ready_methods()
        if methods is not None:
            self._methods = methods

    async def _refresh_methods(self) -> None:
        with contextlib.suppress(ApiError):
            await self._check_health()

    def _save(self, job: Job) -> None:
        """Persist ``job``; a write error is only logged (the in-memory job is authoritative)."""
        try:
            write_job(self._root / job.id, job)
        except OSError:
            logger.exception("job %s: could not save its %s state", job.id, job.state)

    def _settle(self, job: Job, state: JobState, error: dict[str, Any] | None) -> None:
        """Move ``job`` to a terminal state and persist it."""
        job.state, job.error, job.finished_at = state, error, now_iso()
        self._save(job)
