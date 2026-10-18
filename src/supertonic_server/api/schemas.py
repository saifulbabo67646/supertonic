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
