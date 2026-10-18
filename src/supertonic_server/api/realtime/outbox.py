"""Ordered, size-aware queue of outgoing realtime events with a single writer."""

from __future__ import annotations

import asyncio
import json
import logging
from collections import deque
from collections.abc import Awaitable, Callable
from typing import Any

from starlette.websockets import WebSocketDisconnect

logger = logging.getLogger(__name__)

HIGH_WATER_BYTES = 4 * 1024 * 1024
"""Encoded bytes waiting to be sent above which synthesis pauses (backpressure)."""

AUDIO_EVENTS = frozenset(
    {"conversation.item.audio_output.delta", "conversation.item.audio_output.done"}
)


class Outbox:
    """Events are encoded once, sent whole and in :meth:`put` order by :meth:`run`.

    While more than ``high_water`` bytes are pending (queued plus the frame being sent),
    :meth:`wait_for_room` blocks, so a client that stops reading stops synthesis instead of
    growing server memory.

    Args:
        high_water: Pending-bytes limit; defaults to :data:`HIGH_WATER_BYTES`.
    """

    def __init__(self, high_water: int | None = None) -> None:
        self.high_water = HIGH_WATER_BYTES if high_water is None else high_water
        self._queue: deque[tuple[str, str | None, str]] = deque()
        self._queued_bytes = 0
        self._sending = 0
        self._wake = asyncio.Event()
        self._room = asyncio.Event()
        self._room.set()

    @property
    def pending_bytes(self) -> int:
        """Encoded bytes queued or being sent."""
        return self._queued_bytes + self._sending

    def put(self, event: dict[str, Any]) -> None:
        """Encode and queue ``event``."""
        text = json.dumps(event)
        self._queue.append((event["type"], event.get("context_id"), text))
        self._queued_bytes += len(text)
        self._wake.set()
        self._update_room()

    def discard_audio(self, context_id: str) -> None:
        """Drop unsent audio deltas and ``done`` events of ``context_id``."""
        self._queue = deque(
            e for e in self._queue if not (e[0] in AUDIO_EVENTS and e[1] == context_id)
        )
        self._queued_bytes = sum(len(e[2]) for e in self._queue)
        self._update_room()

    async def wait_for_room(self) -> None:
        """Return once pending bytes are at or below the high-water mark."""
        while self.pending_bytes > self.high_water:
            await self._room.wait()

    async def run(self, send: Callable[[str], Awaitable[None]]) -> None:
        """Send queued events forever; returns quietly when the socket is gone."""
        while True:
            while not self._queue:
                self._wake.clear()
                await self._wake.wait()
            _, _, text = self._queue.popleft()
            self._queued_bytes -= len(text)
            self._sending = len(text)
            try:
                await send(text)
            except (WebSocketDisconnect, RuntimeError, OSError) as exc:
                logger.debug("realtime socket closed while sending: %r", exc)
                return
            finally:
                self._sending = 0
                self._update_room()

    def _update_room(self) -> None:
        if self.pending_bytes > self.high_water:
            self._room.clear()
        else:
            self._room.set()
