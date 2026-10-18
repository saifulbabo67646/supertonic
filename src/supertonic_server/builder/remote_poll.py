"""Following remote jobs: one poller task per active mirror job, and the final import.

:class:`RemotePolling` is mixed into :class:`~.remote.RemoteBuilder`; it relies on the
attributes and the ``_save``/``_settle`` methods declared below.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from supertonic_server.builder import remote_import
from supertonic_server.builder.models import Job, JobState
from supertonic_server.builder.remote_http import BuilderClient, Unreachable
from supertonic_server.core.errors import ApiError
from supertonic_server.core.scrub import scrub_paths
from supertonic_server.voices import Voice, VoiceLibrary

logger = logging.getLogger(__name__)

TERMINAL = frozenset({"succeeded", "failed", "cancelled"})
POLL_ERRORS = (Unreachable, ApiError, ValueError, KeyError, TypeError)
"""A poll that raises one of these counts as a failed contact with the builder."""


class RemotePolling:
    """Poll remote jobs, mirror their state and import finished voices exactly once."""

    host: str
    label: str
    _client: BuilderClient
    _library: VoiceLibrary
    _poll_s: float
    _lost_after_s: float
    _pollers: dict[str, asyncio.Task[None]]
    _importing: set[str]

    def _save(self, job: Job) -> None:
        raise NotImplementedError

    def _settle(self, job: Job, state: JobState, error: dict[str, Any] | None) -> None:
        raise NotImplementedError

    def _follow(self, job: Job, *, immediate: bool = False) -> None:
        """Start polling ``job`` unless a poller for it is already running."""
        current = self._pollers.get(job.id)
        if current is not None and not current.done():
            return
        task = asyncio.create_task(self._poll(job, immediate), name=f"remote-build-{job.id}")
        self._pollers[job.id] = task

        def forget(done: asyncio.Task[None]) -> None:
            if self._pollers.get(job.id) is done:
                del self._pollers[job.id]

        task.add_done_callback(forget)

    async def _poll(self, job: Job, immediate: bool) -> None:
        last_ok = time.monotonic()
        while job.state not in TERMINAL:
            if not immediate:
                await asyncio.sleep(self._poll_s)
            immediate = False
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
                error = {"code": "internal_error", "message": scrub_paths(str(exc))}
                self._settle(job, "failed", error)

    async def _poll_once(self, job: Job) -> None:
        if job.remote_id is None:
            raise TypeError("job has no remote id")
        remote = Job.from_dict(await self._client.job(job.remote_id))
        if remote.state == "succeeded":
            if remote.voice_id is None:
                raise ValueError("the remote job succeeded without a voice")
            await self._import(job, job.remote_id, remote.voice_id)
        elif remote.state in ("failed", "cancelled"):
            self._settle(job, remote.state, remote.error)
        else:
            before = job.to_dict()
            job.state, job.started_at = remote.state, remote.started_at
            job.progress, job.stopping = remote.progress, remote.stopping
            if job.to_dict() != before:
                self._save(job)

    async def _import(self, job: Job, remote_id: str, remote_voice_id: str) -> None:
        """Fetch the remote voice and import it; fetch errors propagate (the poll retries)."""
        client, label = self._client, self.label
        style, extra = await remote_import.fetch(client, remote_voice_id, label, remote_id)
        store = remote_import.store
        work = asyncio.ensure_future(asyncio.to_thread(store, self._library, job, style, extra))
        self._importing.add(job.id)
        try:
            outcome = await asyncio.shield(work)
        except asyncio.CancelledError:  # close(): finish the import, never half-record it
            self._record(job, await work, remote_voice_id)
            raise
        finally:
            self._importing.discard(job.id)
        self._record(job, outcome, remote_voice_id)

    def _record(self, job: Job, outcome: Voice | str, remote_voice_id: str) -> None:
        if isinstance(outcome, str):
            self._settle(job, "failed", {"code": "import_failed", "message": outcome})
            return
        job.voice_id, job.remote_voice_id = outcome.id, remote_voice_id
        self._settle(job, "succeeded", None)
