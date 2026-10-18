"""OpenAI-compatible speech endpoint with sentence-level streaming."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncGenerator
from typing import Any

import numpy as np
from fastapi import APIRouter, Response
from fastapi.responses import StreamingResponse
from supertonic.config import DEFAULT_SILENCE_DURATION

from supertonic_server.api.routes._common import State
from supertonic_server.api.schemas import SpeechRequest
from supertonic_server.audio import ALLOWED_RATES, MIME, encode, resample, to_pcm16, wav_header
from supertonic_server.core.errors import ApiError
from supertonic_server.engine import PRIORITY_DEFAULT, Chunk
from supertonic_server.text import get_language

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1")

PCM_DEFAULT_RATE = 24000


def _target_rate(req: SpeechRequest) -> int:
    rate = req.sample_rate or (PCM_DEFAULT_RATE if req.response_format == "pcm" else 44100)
    if rate not in ALLOWED_RATES:
        raise ApiError(
            400,
            "invalid_sample_rate",
            f"sample_rate must be one of {sorted(ALLOWED_RATES)}, got {rate}",
            param="sample_rate",
        )
    return rate


def _pcm(audio: np.ndarray, src_rate: int, rate: int) -> bytes:
    """Resample one sentence and convert it to PCM16 (CPU work; run in a thread)."""
    return to_pcm16(resample(audio, src_rate, rate))


def _encode_render(audio: np.ndarray, src_rate: int, rate: int, fmt: str) -> bytes:
    """Resample and encode a full render (CPU work and ffmpeg; run in a thread)."""
    return encode(resample(audio, src_rate, rate), rate, fmt)


async def _body(
    first: Chunk,
    chunks: AsyncGenerator[Chunk, None],
    src_rate: int,
    rate: int,
    header: bool,
) -> AsyncGenerator[bytes, None]:
    """Yield an optional streaming WAV header, then PCM16 for each sentence.

    The engine stream is always closed, also when the client disconnects mid-stream.
    """
    gap = to_pcm16(np.zeros(int(DEFAULT_SILENCE_DURATION * rate), dtype=np.float32))
    try:
        if header:
            yield wav_header(rate, None)
        chunk: Chunk | None = first
        while chunk is not None:
            if chunk is not first:
                yield gap
            yield await asyncio.to_thread(_pcm, chunk.audio, src_rate, rate)
            chunk = await anext(chunks, None)
    finally:
        await chunks.aclose()


@router.post("/audio/speech")
async def speech(req: SpeechRequest, state: State) -> Response:
    """Synthesise ``input``; ``pcm`` and ``wav`` are streamed per sentence."""
    voice = state.library.resolve(req.voice)
    get_language(req.language)
    rate = _target_rate(req)
    style = state.library.style(voice.id)
    engine = state.engine
    headers = {"X-Sample-Rate": str(rate), "X-Voice-Id": voice.id}
    media = MIME[req.response_format]
    args = (req.input, style, req.language, req.speed, req.total_steps, PRIORITY_DEFAULT)

    if req.response_format not in ("pcm", "wav"):
        audio, _ = await engine.render(*args)
        fmt = req.response_format
        data = await asyncio.to_thread(_encode_render, audio, engine.sample_rate, rate, fmt)
        return Response(data, media_type=media, headers=headers)

    chunks = engine.stream(*args)
    try:
        # Pulling the first sentence surfaces every validation error as JSON before any
        # byte of the response is sent.
        first = await anext(chunks)
    except BaseException:
        await chunks.aclose()
        raise
    body = _body(first, chunks, engine.sample_rate, rate, req.response_format == "wav")
    return StreamingResponse(body, media_type=media, headers=headers)


@router.get("/models")
async def models() -> dict[str, Any]:
    """List the single served model, in OpenAI's list format."""
    return {
        "object": "list",
        "data": [{"id": "supertonic-3", "object": "model", "owned_by": "supertone"}],
    }
