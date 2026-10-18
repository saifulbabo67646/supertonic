"""``POST /v1/tts/timestamps``: audio plus estimated word timings."""

from __future__ import annotations

import base64

from fastapi import APIRouter
from supertonic.config import DEFAULT_SILENCE_DURATION

from supertonic_server.api.routes._common import State
from supertonic_server.api.schemas import TimedText, TimestampsRequest, TimestampsResponse
from supertonic_server.audio import encode, estimate_spans
from supertonic_server.core.errors import ApiError
from supertonic_server.engine import PRIORITY_DEFAULT
from supertonic_server.text import get_language

router = APIRouter(prefix="/v1")

FORMATS = ("wav", "mp3")


@router.post("/tts/timestamps")
async def timestamps(req: TimestampsRequest, state: State) -> TimestampsResponse:
    """Synthesise ``text`` and return base64 audio with estimated segment and word timings."""
    if req.response_format not in FORMATS:
        raise ApiError(
            400,
            "invalid_response_format",
            f"response_format must be one of {list(FORMATS)}, got '{req.response_format}'",
            param="response_format",
        )
    voice = state.library.resolve(req.voice)
    lang = get_language(req.language)
    engine = state.engine
    audio, chunks = await engine.render(
        req.text,
        state.library.style(voice.id),
        lang.code,
        req.speed,
        req.total_steps,
        PRIORITY_DEFAULT,
    )
    rate = engine.sample_rate
    gap_ms = round(DEFAULT_SILENCE_DURATION * 1000)
    segments: list[TimedText] = []
    words: list[TimedText] = []
    cursor = 0
    for chunk in chunks:
        end = cursor + round(len(chunk.audio) * 1000 / rate)
        segments.append(TimedText(text=chunk.text, start_ms=cursor, end_ms=end))
        for s in estimate_spans(chunk.text, chunk.audio, rate, lang.spaced, cursor):
            words.append(TimedText(text=s.text, start_ms=s.start_ms, end_ms=s.end_ms))
        cursor = end + gap_ms
    data = encode(audio, rate, req.response_format)
    return TimestampsResponse(
        audio_base64=base64.b64encode(data).decode("ascii"),
        format=req.response_format,
        sample_rate=rate,
        duration_ms=max(round(len(audio) * 1000 / rate), cursor - gap_ms),
        voice=voice.id,
        language=lang.code,
        timing_unit="word" if lang.spaced else "character",
        segments=segments,
        words=words,
    )
