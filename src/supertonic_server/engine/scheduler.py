"""Priority scheduler running blocking synthesis jobs on a bounded thread pool."""

from __future__ import annotations

import asyncio
import heapq
import itertools
import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from functools import partial
from typing import Any, Generic, TypeVar

from supertonic_server.core.errors import ApiError

logger = logging.getLogger(__name__)

T = TypeVar("T")

PRIORITY_REALTIME = 0
"""Priority for interactive (WebSocket / streaming) work; runs before everything else."""

PRIORITY_DEFAULT = 10
"""Priority for ordinary requests."""


class ServerBusy(ApiError):
    """Raised when the job queue is full or the scheduler is shut down (HTTP 503)."""

    def __init__(self, message: str = "Server is busy; retry shortly") -> None:
        super().__init__(503, "server_busy", message, type_="server_error")


@dataclass
class _Job(Generic[T]):
    fn: Callable[[], T]
    future: asyncio.Future[T]
    realtime: bool = False
    started: bool = field(default=False)


class Scheduler:
    """Runs blocking callables on ``workers`` threads, lowest priority value first.

    Jobs of equal priority run in submission order. Admission keeps a reserve for realtime
    work: a :data:`PRIORITY_REALTIME` job is refused only when ``max_queue`` realtime jobs
    are already waiting, while any other job is refused once ``max_queue`` jobs of any
    priority are waiting (running jobs never count). Bulk requests therefore cannot make a
    live session fail with :class:`ServerBusy`. All bookkeeping happens on the event loop
    thread, so no lock is needed.

    Args:
        workers: Number of jobs allowed to run at once.
        max_queue: Maximum number of jobs waiting to start (per admission class, see above).
    """

    def __init__(self, workers: int, max_queue: int) -> None:
        if workers < 1:
            raise ValueError("workers must be >= 1")
        self.workers = workers
        self.max_queue = max_queue
        self._pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="synth")
        self._heap: list[tuple[int, int, _Job[Any]]] = []
        self._seq = itertools.count()
        self._running = 0
        self._waiting_realtime = 0
        self._closed = False

    @property
    def waiting(self) -> int:
        """Number of jobs queued but not yet started."""
        return len(self._heap)

    @property
    def running(self) -> int:
        """Number of jobs currently executing."""
        return self._running

    async def submit(self, fn: Callable[[], T], priority: int) -> T:
        """Queue ``fn`` and return its result once a worker has run it.

        If the caller is cancelled before the job starts, the job is removed and never runs;
        if it has already started, the thread finishes and its result is discarded.

        Raises:
            ServerBusy: The job's admission class is full (see the class docstring), or the
                scheduler is closed.
        """
        if self._closed:
            raise ServerBusy("Server is shutting down")
        realtime = priority <= PRIORITY_REALTIME
        waiting = self._waiting_realtime if realtime else len(self._heap)
        if waiting >= self.max_queue:
            raise ServerBusy()
        job: _Job[T] = _Job(fn, asyncio.get_running_loop().create_future(), realtime=realtime)
        entry: tuple[int, int, _Job[Any]] = (priority, next(self._seq), job)
        heapq.heappush(self._heap, entry)
        self._waiting_realtime += realtime
        self._dispatch()
        try:
            return await job.future
        except asyncio.CancelledError:
            if not job.started and entry in self._heap:
                self._heap.remove(entry)
                heapq.heapify(self._heap)
                self._waiting_realtime -= realtime
            raise

    def close(self) -> None:
        """Reject new jobs, fail waiting ones with :class:`ServerBusy` and stop the pool.

        Running jobs are allowed to finish; this does not block. Call it from the event
        loop thread.
        """
        self._closed = True
        heap, self._heap = self._heap, []
        self._waiting_realtime = 0
        for _, _, job in heap:
            if not job.future.done():
                job.future.set_exception(ServerBusy("Server is shutting down"))
        self._pool.shutdown(wait=False, cancel_futures=True)

    def _dispatch(self) -> None:
        if self._closed:
            return
        loop = asyncio.get_running_loop()
        while self._running < self.workers and self._heap:
            _, _, job = heapq.heappop(self._heap)
            self._waiting_realtime -= job.realtime
            if job.future.done():  # defensive: cancelled between scheduling steps
                continue
            job.started = True
            self._running += 1
            exec_future = loop.run_in_executor(self._pool, job.fn)
            exec_future.add_done_callback(partial(self._finished, job))

    def _finished(self, job: _Job[Any], exec_future: asyncio.Future[Any]) -> None:
        self._running -= 1
        if exec_future.cancelled():
            if not job.future.done():
                job.future.set_exception(ServerBusy("Server is shutting down"))
        else:
            exc = exec_future.exception()  # always retrieve, even if nobody is waiting
            if job.future.done():
                if exc is not None:
                    logger.debug("discarded failure of abandoned job: %r", exc)
            elif exc is not None:
                job.future.set_exception(exc)
            else:
                job.future.set_result(exec_future.result())
        self._dispatch()
