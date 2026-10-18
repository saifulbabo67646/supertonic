"""Forward voice builds to a remote builder and import the finished voices locally.

A machine without a GPU sets ``SUPERTONIC_BUILDER_URL`` to another Supertonic server that
has a local builder. :class:`RemoteBuilder` checks that server's health, forwards the build,
keeps a local mirror job (``data_dir/jobs/<id>/job.json`` with ``remote_id``) and polls the
remote job. When it succeeds, the style and its ``build`` metadata are fetched and imported
into the local library with ``builder: "remote:<host>"``.

If polling keeps failing for ``lost_after_s`` the local job fails with ``builder_lost`` and
nothing is imported (the remote may still finish; its voice stays there). After a restart,
mirror jobs still queued or running resume polling: the remote job kept running.
"""

from __future__ import annotations

import asyncio
import builtins
import contextlib
import logging
import time
import uuid
from collections.abc import Sequence
from datetime import timedelta
from pathlib import Path
from typing import Any

import httpx

from supertonic_server.builder.jobstore import load_jobs, now_iso, write_job
from supertonic_server.builder.models import BUILD_METHODS, BuildMethod, BuildRequest, Job, JobState
from supertonic_server.builder.remote_http import DEFAULT_TIMEOUT, BuilderClient, Unreachable
from supertonic_server.core import errors
from supertonic_server.core.errors import ApiError
from supertonic_server.voices import Voice, VoiceLibrary

logger = logging.getLogger(__name__)

PRUNE_AFTER = timedelta(days=7)
TERMINAL = frozenset({"succeeded", "failed", "cancelled"})
POLL_ERRORS = (Unreachable, ApiError, ValueError, KeyError, TypeError)
"""A poll that raises one of these counts as a failed contact with the builder."""


class RemoteBuilder:
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
        self._poll_s = poll_s
        self._lost_after_s = lost_after_s
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
        """
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
        """Forward a build to the remote and start following it.

        The remote validates the request (its errors come back unchanged, e.g.
        ``consent_required``, ``invalid_reference_audio``, ``method_unavailable``).
        ``builder_label`` is ignored: forwarded jobs are always ``remote:<host>``.

        Raises:
            ApiError: 503 ``builder_unavailable`` when the remote is unreachable or has no
                local builder; otherwise the remote's own error.
        """
        if self._closed:
            raise errors.builder_unavailable("Voice builder is shutting down")
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
        self._persist(job)
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
        result is being imported is left to finish.
        """
        job = self.get(job_id)
        if job.state in TERMINAL:
            return job
        poller = self._pollers.pop(job_id, None)
        if poller is not None:
            if job_id in self._importing:
                await asyncio.gather(poller, return_exceptions=True)
                return job
            poller.cancel()
            await asyncio.gather(poller, return_exceptions=True)
        if job.state in TERMINAL or job.remote_id is None:
            return job
        try:
            remote = Job.from_dict(await self._client.cancel(job.remote_id))
        except POLL_ERRORS as exc:
            logger.warning("job %s: could not cancel it on %s: %s", job.id, self.host, exc)
        else:
            if remote.state in ("succeeded", "failed"):  # it finished first: settle as usual
                self._follow(job)
                return job
        self._settle(job, "cancelled", None)
        return job

    async def finish(self, job_id: str) -> Job:
        """Ask the remote job to save its best result now.

        Raises:
            ApiError: 409 ``job_not_running`` for a queued job; 503 ``builder_unavailable``
                when the remote cannot be reached.
        """
        job = self.get(job_id)
        if job.state in TERMINAL or job.remote_id is None:
            return job
        try:
            remote = Job.from_dict(await self._client.finish(job.remote_id))
        except Unreachable as exc:
            raise self._client.unreachable(str(exc)) from exc
        except ApiError as exc:
            if exc.code == "job_not_running":
                raise errors.job_not_running(job_id) from exc
            raise
        if remote.stopping and not job.stopping:
            job.stopping = True
            self._persist(job)
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

    def _follow(self, job: Job) -> None:
        task = asyncio.create_task(self._poll(job), name=f"remote-build-{job.id}")
        self._pollers[job.id] = task

        def forget(done: asyncio.Task[None]) -> None:
            if self._pollers.get(job.id) is done:
                del self._pollers[job.id]

        task.add_done_callback(forget)

    async def _poll(self, job: Job) -> None:
        last_ok = time.monotonic()
        while job.state not in TERMINAL:
            await asyncio.sleep(self._poll_s)
            try:
                await self._poll_once(job)
                last_ok = time.monotonic()
            except POLL_ERRORS as exc:
                gone = isinstance(exc, ApiError) and exc.code == "job_not_found"
                if gone or time.monotonic() - last_ok >= self._lost_after_s:
                    why = "it no longer knows this job" if gone else str(exc)
                    message = f"Lost the voice builder at {self.host}: {why}"
                    self._settle(job, "failed", {"code": "builder_lost", "message": message})
            except Exception as exc:  # never leave a mirror job hanging
                logger.exception("job %s: polling %s crashed", job.id, self.host)
                self._settle(job, "failed", {"code": "internal_error", "message": str(exc)})

    async def _poll_once(self, job: Job) -> None:
        if job.remote_id is None:
            raise TypeError("job has no remote id")
        remote = Job.from_dict(await self._client.job(job.remote_id))
        if remote.state == "succeeded":
            if remote.voice_id is None:
                raise ValueError("the remote job succeeded without a voice")
            await self._import(job, remote.voice_id)
            return
        if remote.state in ("failed", "cancelled"):
            self._settle(job, remote.state, remote.error)
            return
        before = job.to_dict()
        job.state, job.started_at = remote.state, remote.started_at
        job.progress, job.stopping = remote.progress, remote.stopping
        if job.to_dict() != before:
            self._persist(job)

    async def _import(self, job: Job, remote_voice_id: str) -> None:
        """Fetch the remote voice and import it; fetch errors propagate (the poll retries)."""
        meta = await self._client.voice(remote_voice_id)
        style = await self._client.style(remote_voice_id)
        build = meta.get("build")
        extra = {**(build if isinstance(build, dict) else {}), "builder": self.label}
        work = asyncio.ensure_future(asyncio.to_thread(self._store, job.request, style, extra))
        self._importing.add(job.id)
        try:
            outcome = await asyncio.shield(work)
        except asyncio.CancelledError:  # close(): finish the import, never half-record it
            self._record(job, await work, remote_voice_id)
            raise
        finally:
            self._importing.discard(job.id)
        self._record(job, outcome, remote_voice_id)

    def _store(
        self, req: BuildRequest, style: dict[str, Any], extra: dict[str, Any]
    ) -> Voice | str:
        """Import the voice (in a thread); return it, or why it could not be stored."""
        try:
            return self._library.import_style(
                style, req.name.strip(), req.description, req.tags, req.source_note, extra=extra
            )
        except (OSError, ValueError, ApiError) as exc:
            return exc.message if isinstance(exc, ApiError) else str(exc)

    def _record(self, job: Job, outcome: Voice | str, remote_voice_id: str) -> None:
        if isinstance(outcome, str):
            self._settle(job, "failed", {"code": "import_failed", "message": outcome})
            return
        job.voice_id, job.remote_voice_id = outcome.id, remote_voice_id
        self._settle(job, "succeeded", None)

    def _persist(self, job: Job) -> None:
        write_job(self._root / job.id, job)

    def _settle(self, job: Job, state: JobState, error: dict[str, Any] | None) -> None:
        """Move ``job`` to a terminal state and persist it (a write error is only logged)."""
        job.state, job.error, job.finished_at = state, error, now_iso()
        try:
            self._persist(job)
        except OSError:
            logger.exception("job %s: could not save its %s state", job.id, state)
