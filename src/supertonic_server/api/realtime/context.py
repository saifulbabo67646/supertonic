"""Per-context state of a realtime session."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING

from supertonic_server.text import SentenceBuffer

if TYPE_CHECKING:
    from supertonic_server.api.realtime.params import Voicing


@dataclass(frozen=True)
class Entry:
    """A queued sentence of an item (``text is None`` marks the item's end)."""

    item_id: str
    text: str | None
    voicing: Voicing


class Context:
    """State of one ``context_id``: buffer, sentence queue, current item and consumer."""

    def __init__(self, context_id: str, voicing: Voicing, max_partial: int) -> None:
        self.id = context_id
        self.voicing = voicing
        self.max_partial = max_partial
        self.buffer = SentenceBuffer(max_partial, lang=voicing.language)
        self.queue: asyncio.Queue[Entry] = asyncio.Queue()
        self.item_id: str | None = None
        self.failed_item: str | None = None
        self.task: asyncio.Task[None] | None = None
        self.queued_chars = 0
        """Characters of queued sentences not yet taken by the consumer."""

    @property
    def pending_chars(self) -> int:
        """Buffered plus queued characters that have not been synthesised yet."""
        return len(self.buffer) + self.queued_chars

    def set_voicing(self, voicing: Voicing) -> list[str]:
        """Switch settings; buffered text moves to a buffer for the new language.

        Returns sentences that became complete while moving the text.
        """
        if voicing.language == self.voicing.language:
            self.voicing = voicing
            return []
        pending = " ".join(self.buffer.flush())
        self.voicing = voicing
        self.buffer = SentenceBuffer(self.max_partial, lang=voicing.language)
        return self.buffer.append(pending)

    async def reset(self) -> None:
        """Stop the consumer and drop everything buffered, queued or in flight."""
        task, self.task = self.task, None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        self.buffer.clear()
        self.queue = asyncio.Queue()
        self.item_id = None
        self.failed_item = None
        self.queued_chars = 0
