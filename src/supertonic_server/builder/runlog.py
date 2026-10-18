"""Follow one worker process: parse its JSON-lines stdout, keep its stderr, enforce the timeout."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections import deque
from collections.abc import Callable
from dataclasses import fields
from pathlib import Path
from types import TracebackType
from typing import IO, Any, get_args

from supertonic_server.builder.models import Job, Progress, Stage
from supertonic_server.builder.process import KILL_WAIT_S, kill_group_stragglers, kill_tree

logger = logging.getLogger(__name__)

PERSIST_EVERY_S = 1.0
TAIL_LINES = 20
MAX_MESSAGE = 500
_PROGRESS_KEYS = tuple(f.name for f in fields(Progress))
_STAGES = frozenset(get_args(Stage))


class RunLog:
    """Reads a worker's output into ``job.progress``, ``progress.jsonl`` and ``worker.log``.

    Args:
        folder: The job directory.
        job: Updated in place with each progress event.
        persist: Saves the job; called at most once per second for progress.
    """

    def __init__(self, folder: Path, job: Job, persist: Callable[[], None]) -> None:
        self._folder = folder
        self._job = job
        self._persist = persist
        self._last_persist = float("-inf")
        self._tail: deque[str] = deque(maxlen=TAIL_LINES)
        self._progress: IO[str] | None = None
        self._log: IO[bytes] | None = None
        self.report: dict[str, Any] | None = None
        self.error: dict[str, Any] | None = None
        self.problem: str | None = None
        """First failure while handling the worker's output, if any."""
        self._problems = 0

    def __enter__(self) -> RunLog:
        self._progress = (self._folder / "progress.jsonl").open("a", encoding="utf-8")
        self._log = (self._folder / "worker.log").open("ab")
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        for fh in (self._progress, self._log):
            if fh is not None:
                fh.close()

    async def follow(self, proc: asyncio.subprocess.Process, timeout_s: float) -> bool:
        """Read until the worker exits (killing its tree after ``timeout_s``).

        Returns:
            True when the timeout ended the run.
        """
        assert proc.stdout is not None and proc.stderr is not None
        readers = [
            asyncio.create_task(self._read(proc.stdout, self._on_stdout)),
            asyncio.create_task(self._read(proc.stderr, self._on_stderr)),
        ]
        timed_out = False
        try:
            try:
                async with asyncio.timeout(timeout_s):
                    await proc.wait()
            except TimeoutError:
                timed_out = True
        finally:  # also on cancellation: never leave a worker behind
            if proc.returncode is None:
                await kill_tree(proc)
                await proc.wait()
            _, pending = await asyncio.wait(readers, timeout=KILL_WAIT_S)
            if pending:  # a descendant still holds the pipes
                await kill_group_stragglers(proc)
                for task in pending:
                    task.cancel()
                await asyncio.gather(*pending, return_exceptions=True)
            for task in readers:
                if not task.cancelled() and (exc := task.exception()) is not None:
                    self._note(exc)
        if self._problems > 1:
            count = self._problems
            logger.error("job %s: %d worker output lines not recorded", self._job.id, count)
        return timed_out

    def failure(self, returncode: int | None) -> dict[str, Any]:
        """The ``{code, message}`` for a failed run.

        The last error event; else, when the worker exited 0 but its result was lost to an
        output-handling problem, that problem; else the last stderr line or the exit code.
        """
        if self.error is not None:
            return self.error
        if self.problem is not None and (returncode == 0 or not self._tail):
            message = self.problem
        elif self._tail:
            message = self._tail[-1]
        else:
            message = f"worker exited with code {returncode}"
        return {"code": "worker_failed", "message": message[:MAX_MESSAGE]}

    def _note(self, exc: BaseException) -> None:
        """Record an output-handling failure (logged once per run, counted after that)."""
        self._problems += 1
        if self.problem is None:
            self.problem = f"could not record worker output: {type(exc).__name__}: {exc}"
            logger.error("job %s: %s", self._job.id, self.problem, exc_info=exc)

    async def _read(self, stream: asyncio.StreamReader, handle: Callable[[bytes], None]) -> None:
        """Hand each line to ``handle``; whatever fails, keep draining so the worker can't block."""
        try:
            while True:
                try:
                    raw = await stream.readline()
                except ValueError:  # longer than the stream limit; the rest of it is dropped
                    raw = b"<overlong line skipped>\n"
                else:
                    if not raw:
                        return
                try:
                    handle(raw)
                except Exception as exc:  # e.g. disk full while writing the logs
                    self._note(exc)
        except Exception as exc:  # the stream itself failed: discard the rest
            self._note(exc)
            with contextlib.suppress(Exception):
                while await stream.read(65536):
                    pass

    def _write_log(self, raw: bytes) -> None:
        if self._log is not None:
            self._log.write(raw if raw.endswith(b"\n") else raw + b"\n")
            self._log.flush()

    def _on_stderr(self, raw: bytes) -> None:
        self._write_log(raw)
        line = raw.decode("utf-8", "replace").strip()
        if line:
            self._tail.append(line)

    def _on_stdout(self, raw: bytes) -> None:
        line = raw.decode("utf-8", "replace").strip()
        if not line:
            return
        try:
            event = json.loads(line)
        except ValueError:
            event = None
        kind = event.get("type") if isinstance(event, dict) else None
        if kind == "progress" and isinstance(event, dict):
            self._on_progress(event, line)
        elif kind == "done" and isinstance(event, dict) and isinstance(event.get("report"), dict):
            self.report = event["report"]
        elif kind == "error" and isinstance(event, dict):
            message = str(event.get("message", ""))[:MAX_MESSAGE]
            self.error = {"code": str(event.get("code", "worker_failed")), "message": message}
        else:
            self._write_log(b"[stdout] " + raw)

    def _on_progress(self, event: dict[str, Any], line: str) -> None:
        if event.get("stage") not in _STAGES:
            self._write_log(b"[stdout] " + line.encode("utf-8"))
            return
        values: dict[str, Any] = {k: event.get(k) for k in _PROGRESS_KEYS}
        self._job.progress = Progress(**values)
        if self._progress is not None:
            self._progress.write(line + "\n")
            self._progress.flush()
        now = asyncio.get_running_loop().time()
        if now - self._last_persist >= PERSIST_EVERY_S:
            self._last_persist = now
            self._persist()
