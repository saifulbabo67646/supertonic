"""Connection parameters and per-context voice settings of a realtime session."""

from __future__ import annotations

import hmac
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from supertonic_server.api.deps import bearer_token
from supertonic_server.audio import ALLOWED_RATES
from supertonic_server.core.errors import ApiError
from supertonic_server.engine.engine import DEFAULT_SPEED, MAX_SPEED, MIN_SPEED
from supertonic_server.text import get_language

if TYPE_CHECKING:
    from starlette.datastructures import QueryParams
    from starlette.requests import HTTPConnection
    from supertonic.core import Style

    from supertonic_server.api.deps import AppState
    from supertonic_server.api.realtime.protocol import SessionPatch
    from supertonic_server.voices import VoiceLibrary

DEFAULT_SAMPLE_RATE = 24000
DEFAULT_MAX_PARTIAL = 250


@dataclass(frozen=True)
class Voicing:
    """Voice, language and speed used to synthesise a context's sentences."""

    voice: str
    style: Style
    language: str
    speed: float

    def patched(self, patch: SessionPatch, library: VoiceLibrary) -> Voicing:
        """Return a copy with the fields set in ``patch`` validated and applied.

        Raises:
            ApiError: ``voice_not_found``/``ambiguous_voice``, ``language_not_supported`` or
                ``invalid_speed``.
        """
        out = self
        if patch.voice is not None:
            vid = library.resolve(patch.voice).id
            out = replace(out, voice=vid, style=library.style(vid))
        if patch.language is not None:
            out = replace(out, language=get_language(patch.language).code)
        if patch.speed is not None:
            out = replace(out, speed=check_speed(patch.speed))
        return out


@dataclass(frozen=True)
class ConnectParams:
    """Validated query parameters of a realtime connection."""

    voicing: Voicing
    sample_rate: int
    max_partial_length: int


def check_speed(speed: float) -> float:
    """Return ``speed`` or raise 400 ``invalid_speed`` when outside 0.7-2.0."""
    if not MIN_SPEED <= speed <= MAX_SPEED:
        raise ApiError(
            400,
            "invalid_speed",
            f"speed must be between {MIN_SPEED} and {MAX_SPEED}, got {speed}",
            param="speed",
        )
    return speed


def check_key(conn: HTTPConnection, expected: str | None) -> None:
    """Accept a bearer header or ``?api_key=``; raise ``invalid_api_key`` otherwise."""
    if not expected:
        return
    supplied = bearer_token(conn) or conn.query_params.get("api_key", "")
    if not hmac.compare_digest(supplied.encode(), expected.encode()):
        raise ApiError(
            401, "invalid_api_key", "Incorrect or missing API key", type_="authentication_error"
        )


def _number(query: QueryParams, name: str, default: str, kind: type[float] | type[int]) -> float:
    raw = query.get(name, default)
    try:
        return kind(raw)
    except ValueError:
        raise ApiError(
            400, f"invalid_{name}", f"{name} must be a number, got {raw!r}", name
        ) from None


def parse_params(query: QueryParams, state: AppState) -> ConnectParams:
    """Validate the connection query (``voice``, ``language``, ``speed``, ...).

    ``model`` is accepted and ignored: only Supertonic 3 is served.

    Raises:
        ApiError: With the code of the first invalid parameter.
    """
    library = state.library
    vid = library.resolve(query.get("voice") or state.settings.default_voice).id
    language = get_language(query.get("language", "en")).code
    speed = check_speed(_number(query, "speed", str(DEFAULT_SPEED), float))
    rate = int(_number(query, "sample_rate", str(DEFAULT_SAMPLE_RATE), int))
    if rate not in ALLOWED_RATES:
        raise ApiError(
            400,
            "invalid_sample_rate",
            f"sample_rate must be one of {sorted(ALLOWED_RATES)}, got {rate}",
            param="sample_rate",
        )
    partial = int(_number(query, "max_partial_length", str(DEFAULT_MAX_PARTIAL), int))
    if partial < 1:
        raise ApiError(
            400,
            "invalid_max_partial_length",
            f"max_partial_length must be at least 1, got {partial}",
            param="max_partial_length",
        )
    voicing = Voicing(vid, library.style(vid), language, speed)
    return ConnectParams(voicing, rate, partial)
