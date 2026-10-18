"""Sentence-level synthesis: validation, streaming with lookahead and full renders."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncGenerator
from dataclasses import dataclass

import numpy as np
from supertonic.config import DEFAULT_SILENCE_DURATION
from supertonic.core import Style

from supertonic_server.core.errors import ApiError
from supertonic_server.engine.model import SynthModel
from supertonic_server.engine.scheduler import PRIORITY_DEFAULT, Scheduler
from supertonic_server.text import sanitize, split_sentences

logger = logging.getLogger(__name__)

MAX_INPUT_CHARS = 100_000
MIN_SPEED, MAX_SPEED = 0.7, 2.0
MIN_STEPS, MAX_STEPS = 1, 100
DEFAULT_SPEED = 1.05
DEFAULT_STEPS = 8


@dataclass
class Chunk:
    """One synthesised sentence: mono float32 audio at the model's native rate."""

    text: str
    audio: np.ndarray


class Engine:
    """Synthesises text sentence by sentence through a shared :class:`Scheduler`.

    Args:
        model: The synthesis model (shared by all worker threads).
        scheduler: Scheduler that runs model calls.
    """

    def __init__(self, model: SynthModel, scheduler: Scheduler) -> None:
        self.model = model
        self.scheduler = scheduler

    @property
    def sample_rate(self) -> int:
        """Native output sample rate of the model (Hz)."""
        return self.model.sample_rate

    def prepare(self, text: str, lang: str) -> list[str]:
        """Drop unrenderable characters and split ``text`` into sentences.

        Raises:
            ApiError: 400 ``input_too_long`` above 100 000 characters, 400 ``empty_input``
                when nothing speakable remains.
        """
        if len(text) > MAX_INPUT_CHARS:
            raise ApiError(
                400,
                "input_too_long",
                f"Input is {len(text)} characters; the limit is {MAX_INPUT_CHARS}",
                param="input",
            )
        clean = sanitize(text, lambda t: self.model.text_processor.validate_text(t)[1])
        sentences = split_sentences(clean, lang) if clean else []
        if not sentences:
            raise ApiError(400, "empty_input", "Input contains no speakable text", param="input")
        return sentences

    async def synth(
        self, sentence: str, style: Style, lang: str, speed: float, steps: int, priority: int
    ) -> np.ndarray:
        """Synthesise one prepared sentence and return its trimmed float32 audio.

        Raises:
            ApiError: 400 ``invalid_speed`` / ``invalid_total_steps`` for out-of-range values.
            ServerBusy: The scheduler queue is full.
        """
        _validate(speed, steps)
        return await self.scheduler.submit(
            lambda: self._run(sentence, style, lang, speed, steps), priority
        )

    async def stream(
        self,
        text: str,
        style: Style,
        lang: str,
        speed: float = DEFAULT_SPEED,
        steps: int = DEFAULT_STEPS,
        priority: int = PRIORITY_DEFAULT,
    ) -> AsyncGenerator[Chunk, None]:
        """Yield one :class:`Chunk` per sentence, in order.

        While sentence *i* is being awaited, sentence *i + 1* is already queued (one
        sentence of lookahead). Closing the generator or cancelling the consumer cancels the
        outstanding work, so queued sentences never run.
        """
        _validate(speed, steps)
        sentences = self.prepare(text, lang)
        tasks: list[asyncio.Task[np.ndarray]] = []

        def start(i: int) -> None:
            if i < len(sentences):
                job = self.synth(sentences[i], style, lang, speed, steps, priority)
                tasks.append(asyncio.ensure_future(job))

        try:
            start(0)
            for i, sentence in enumerate(sentences):
                current = tasks[i]
                start(i + 1)
                yield Chunk(sentence, await current)
        finally:
            await _cancel_all(tasks)

    async def render(
        self,
        text: str,
        style: Style,
        lang: str,
        speed: float = DEFAULT_SPEED,
        steps: int = DEFAULT_STEPS,
        priority: int = PRIORITY_DEFAULT,
    ) -> tuple[np.ndarray, list[Chunk]]:
        """Synthesise the whole text; chunks are joined with 300 ms of silence.

        Returns:
            The joined float32 audio and the per-sentence chunks.
        """
        chunks = [c async for c in self.stream(text, style, lang, speed, steps, priority)]
        gap = np.zeros(int(DEFAULT_SILENCE_DURATION * self.sample_rate), dtype=np.float32)
        parts: list[np.ndarray] = []
        for i, chunk in enumerate(chunks):
            if i:
                parts.append(gap)
            parts.append(chunk.audio)
        return np.concatenate(parts).astype(np.float32, copy=False), chunks

    def _run(self, sentence: str, style: Style, lang: str, speed: float, steps: int) -> np.ndarray:
        wav, dur = self.model([sentence], style, steps, speed, lang)
        n = int(float(dur[0]) * self.sample_rate)
        return np.ascontiguousarray(wav[0, :n], dtype=np.float32)


def _validate(speed: float, steps: int) -> None:
    if not MIN_SPEED <= speed <= MAX_SPEED:
        raise ApiError(
            400,
            "invalid_speed",
            f"speed must be between {MIN_SPEED} and {MAX_SPEED}, got {speed}",
            param="speed",
        )
    if not MIN_STEPS <= steps <= MAX_STEPS:
        raise ApiError(
            400,
            "invalid_total_steps",
            f"total_steps must be between {MIN_STEPS} and {MAX_STEPS}, got {steps}",
            param="total_steps",
        )


async def _cancel_all(tasks: list[asyncio.Task[np.ndarray]]) -> None:
    """Cancel unfinished tasks and wait for them so no result or exception goes unretrieved."""
    pending = [t for t in tasks if not t.done()]
    for t in pending:
        t.cancel()
    # Retrieve everything (including exceptions of finished-but-unawaited lookahead tasks).
    await asyncio.gather(*tasks, return_exceptions=True)
