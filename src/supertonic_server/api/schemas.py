"""Request and response models for the HTTP API."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from supertonic_server.engine.engine import DEFAULT_SPEED, DEFAULT_STEPS

ResponseFormat = Literal["mp3", "opus", "aac", "flac", "wav", "pcm"]


class SpeechRequest(BaseModel):
    """Body of ``POST /v1/audio/speech`` (OpenAI-compatible plus Supertonic extensions)."""

    model: str = "supertonic-3"
    input: str
    voice: str
    response_format: ResponseFormat = "mp3"
    speed: float = DEFAULT_SPEED
    instructions: str | None = None
    language: str = "en"
    total_steps: int = DEFAULT_STEPS
    sample_rate: int | None = None


class TimestampsRequest(BaseModel):
    """Body of ``POST /v1/tts/timestamps``."""

    text: str
    voice: str
    language: str = "en"
    speed: float = DEFAULT_SPEED
    total_steps: int = DEFAULT_STEPS
    response_format: str = "wav"


class TimedText(BaseModel):
    """A piece of text with its estimated time range."""

    text: str
    start_ms: int
    end_ms: int


class TimestampsResponse(BaseModel):
    """Audio plus estimated segment and word/character timings."""

    audio_base64: str
    format: str
    sample_rate: int
    duration_ms: int
    voice: str
    language: str
    timing_source: Literal["estimated"] = "estimated"
    timing_unit: Literal["word", "character"]
    segments: list[TimedText]
    words: list[TimedText]


class VoicePatch(BaseModel):
    """Body of ``PATCH /v1/voices/{id}``."""

    name: str | None = None
    description: str | None = None
    tags: list[str] | None = None
