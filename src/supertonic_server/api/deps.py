"""Shared API state, auth dependency and preview generation."""

from __future__ import annotations

import asyncio
import hmac
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import Request
from starlette.requests import HTTPConnection

from supertonic_server.audio import encode
from supertonic_server.core.errors import ApiError
from supertonic_server.engine import PRIORITY_DEFAULT
from supertonic_server.text import get_language

if TYPE_CHECKING:
    from supertonic_server.core.config import Settings
    from supertonic_server.engine import Engine
    from supertonic_server.voices import VoiceLibrary

PREVIEW_STEPS = 8
PREVIEW_SPEED = 1.05


@dataclass
class AppState:
    """Everything request handlers need, stored on ``app.state``."""

    settings: Settings
    engine: Engine
    library: VoiceLibrary
    preview_locks: dict[tuple[str, str], asyncio.Lock] = field(default_factory=dict)


def get_state(request: Request) -> AppState:
    """Return the :class:`AppState` of the running app."""
    state: AppState | None = getattr(request.app.state, "app_state", None)
    if state is None:
        raise ApiError(503, "not_ready", "Model is still loading", type_="server_error")
    return state


def bearer_token(conn: HTTPConnection) -> str:
    """Return the token of an ``Authorization: Bearer`` header, or ``""``."""
    header = conn.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    return token.strip() if scheme.lower() == "bearer" else ""


async def require_key(request: Request) -> None:
    """Reject the request unless it carries the configured API key (if one is set)."""
    key = request.app.state.api_key
    if not key:
        return
    if not hmac.compare_digest(bearer_token(request).encode(), key.encode()):
        raise ApiError(
            401, "invalid_api_key", "Incorrect or missing API key", type_="authentication_error"
        )


async def preview(state: AppState, voice_id: str, lang: str) -> Path:
    """Return the cached preview WAV for a voice and language, rendering it once if missing."""
    get_language(lang)
    state.library.get(voice_id)
    path = state.library.preview_path(voice_id, lang)
    if path.exists():
        return path
    lock = state.preview_locks.setdefault((voice_id, lang), asyncio.Lock())
    async with lock:
        if path.exists():
            return path
        sample = get_language(lang).sample
        style = state.library.style(voice_id)
        audio, _ = await state.engine.render(
            sample, style, lang, PREVIEW_SPEED, PREVIEW_STEPS, PRIORITY_DEFAULT
        )
        data = encode(audio, state.engine.sample_rate, "wav")
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(f".{os.getpid()}.tmp")
        tmp.write_bytes(data)
        tmp.replace(path)
    return path
