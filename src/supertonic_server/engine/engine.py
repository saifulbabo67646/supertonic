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
"""Longest text accepted for streaming synthesis."""
MAX_RENDER_CHARS = 20_000
"""Longest text accepted by :meth:`Engine.render`, which holds the whole result in memory."""
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
        # Sanitising and splitting are linear but can take a while on 100 000 characters.
        sentences = await asyncio.to_thread(self.prepare, text, lang)

        def start(i: int) -> asyncio.Task[np.ndarray] | None:
            if i >= len(sentences):
                return None
            job = self.synth(sentences[i], style, lang, speed, steps, priority)
            return asyncio.ensure_future(job)

        # Only the sentence being awaited and its lookahead are referenced, so finished audio
        # is released as soon as the consumer drops it (bounded memory for long inputs).
        current: asyncio.Task[np.ndarray] | None = None
        lookahead = start(0)
        try:
            for i, sentence in enumerate(sentences):
                current, lookahead = lookahead, start(i + 1)
                assert current is not None
                yield Chunk(sentence, await current)
        finally:
            await _cancel_all([t for t in (current, lookahead) if t is not None])

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

        Each returned chunk's ``audio`` is a view into the joined array, so the result holds
        one copy of the audio, not two.

        Returns:
            The joined float32 audio and the per-sentence chunks.

        Raises:
            ApiError: 400 ``input_too_long`` above :data:`MAX_RENDER_CHARS` characters (the
                message points to streaming), plus everything :meth:`stream` raises.
        """
        if len(text) > MAX_RENDER_CHARS:
            raise ApiError(
                400,
                "input_too_long",
                f"Input is {len(text)} characters; complete files are limited to "
                f'{MAX_RENDER_CHARS}. For longer text use response_format "pcm" or "wav" '
                "on /v1/audio/speech, which stream sentence by sentence.",
                param="input",
            )
        gap = np.zeros(int(DEFAULT_SILENCE_DURATION * self.sample_rate), dtype=np.float32)
        texts: list[str] = []
        parts: list[np.ndarray] = []
        async for chunk in self.stream(text, style, lang, speed, steps, priority):
            if parts:
                parts.append(gap)
            texts.append(chunk.text)
            parts.append(chunk.audio)
        joined = np.concatenate(parts).astype(np.float32, copy=False)
        lengths = [len(a) for a in parts[::2]]
        del parts  # drop the per-sentence arrays; only the joined copy remains
        chunks: list[Chunk] = []
        start = 0
        for sentence, n in zip(texts, lengths, strict=True):
            chunks.append(Chunk(sentence, joined[start : start + n]))
            start += n + len(gap)
        return joined, chunks

    def _run(self, sentence: str, style: Style, lang: str, speed: float, steps: int) -> np.ndarray:
        wav, dur = self.model([sentence], style, steps, speed, lang)
        n = int(float(dur[0]) * self.sample_rate)
        return np.ascontiguousarray(wav[0, :n], dtype=np.float32)


def validate_speed(speed: float) -> float:
    """Return ``speed`` or raise 400 ``invalid_speed`` when outside 0.7-2.0 (never clamped)."""
    if not MIN_SPEED <= speed <= MAX_SPEED:
        raise ApiError(
            400,
            "invalid_speed",
            f"speed must be between {MIN_SPEED} and {MAX_SPEED}, got {speed}",
            param="speed",
        )
    return speed


def validate_steps(steps: int) -> int:
    """Return ``steps`` or raise 400 ``invalid_total_steps`` when outside 1-100."""
    if not MIN_STEPS <= steps <= MAX_STEPS:
        raise ApiError(
            400,
            "invalid_total_steps",
            f"total_steps must be between {MIN_STEPS} and {MAX_STEPS}, got {steps}",
            param="total_steps",
        )
    return steps


def _validate(speed: float, steps: int) -> None:
    validate_speed(speed)
    validate_steps(steps)


async def _cancel_all(tasks: list[asyncio.Task[np.ndarray]]) -> None:
    """Cancel unfinished tasks and wait for them so no result or exception goes unretrieved."""
    pending = [t for t in tasks if not t.done()]
    for t in pending:
        t.cancel()
    # Retrieve everything (including exceptions of finished-but-unawaited lookahead tasks).
    await asyncio.gather(*tasks, return_exceptions=True)
