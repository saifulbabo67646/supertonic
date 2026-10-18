"""Realtime WebSocket event models: client event parsing and server event builders.

Event names follow the Together AI realtime TTS protocol. Every client event may carry a
``context_id`` (default ``"default"``) so one socket can speak several independent
utterances.
"""

from __future__ import annotations

import json
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

from supertonic_server.core.errors import ApiError, error_body

DEFAULT_CONTEXT = "default"
MODEL_ID = "supertonic-3"
MAX_CONTEXT_ID_LENGTH = 128


class _Event(BaseModel):
    model_config = ConfigDict(extra="ignore")


class _ContextEvent(_Event):
    context_id: Annotated[str, Field(min_length=1, max_length=MAX_CONTEXT_ID_LENGTH)] = (
        DEFAULT_CONTEXT
    )


class SessionPatch(_Event):
    """Fields a client may change with ``tts_session.updated``; ``None`` keeps the value."""

    voice: str | None = None
    language: str | None = None
    speed: float | None = None


class SessionUpdate(_Event):
    """``tts_session.updated``: change voice/language/speed of one context, or of all."""

    type: Literal["tts_session.updated"]
    context_id: Annotated[str | None, Field(min_length=1, max_length=MAX_CONTEXT_ID_LENGTH)] = None
    session: SessionPatch = Field(default_factory=SessionPatch)


class Append(_ContextEvent):
    """``input_text_buffer.append``: add text to a context's buffer."""

    type: Literal["input_text_buffer.append"]
    text: str


class Commit(_ContextEvent):
    """``input_text_buffer.commit``: flush the buffer and finish the current item."""

    type: Literal["input_text_buffer.commit"]


class Clear(_ContextEvent):
    """``input_text_buffer.clear``: drop buffered text that has not been emitted yet."""

    type: Literal["input_text_buffer.clear"]


class Cancel(_ContextEvent):
    """``context.cancel``: stop a context immediately (barge-in)."""

    type: Literal["context.cancel"]


ClientEvent = Annotated[
    SessionUpdate | Append | Commit | Clear | Cancel, Field(discriminator="type")
]
_ADAPTER: TypeAdapter[ClientEvent] = TypeAdapter(ClientEvent)
_KNOWN = frozenset(
    {
        "tts_session.updated",
        "input_text_buffer.append",
        "input_text_buffer.commit",
        "input_text_buffer.clear",
        "context.cancel",
    }
)


class EventError(ApiError):
    """A client event could not be parsed; ``context_id`` is set when it was readable."""

    def __init__(
        self, code: str, message: str, param: str | None = None, context_id: str | None = None
    ) -> None:
        super().__init__(400, code, message, param=param)
        self.context_id = context_id


def parse_event(raw: str) -> ClientEvent:
    """Parse one text frame into a client event.

    Raises:
        EventError: ``invalid_event`` for malformed JSON or fields, ``unknown_event`` for an
            unknown ``type``.
    """
    try:
        data = json.loads(raw)
    except ValueError:
        raise EventError("invalid_event", "Message is not valid JSON") from None
    if not isinstance(data, dict):
        raise EventError("invalid_event", "Message must be a JSON object")
    ctx = data.get("context_id")
    ctx = ctx if isinstance(ctx, str) else None
    kind = data.get("type")
    if kind not in _KNOWN:
        raise EventError("unknown_event", f"Unknown event type {kind!r}", "type", ctx)
    try:
        return _ADAPTER.validate_python(data)
    except ValidationError as exc:
        first = exc.errors()[0]
        param = ".".join(str(p) for p in first["loc"][1:]) or None
        raise EventError("invalid_event", str(first["msg"]), param, ctx) from None


def session_info(
    session_id: str, voice: str, language: str, sample_rate: int, speed: float
) -> dict[str, Any]:
    """The ``session`` object of ``session.created`` / ``session.updated``."""
    return {
        "id": session_id,
        "object": "realtime.tts.session",
        "modalities": ["audio"],
        "model": MODEL_ID,
        "voice": voice,
        "language": language,
        "sample_rate": sample_rate,
        "speed": speed,
    }


def session_created(session: dict[str, Any]) -> dict[str, Any]:
    """``session.created``, sent once after the handshake."""
    return {"type": "session.created", "session": session}


def session_updated(session: dict[str, Any], context_id: str | None) -> dict[str, Any]:
    """``session.updated``; ``context_id`` is ``None`` when every context was updated."""
    return {"type": "session.updated", "context_id": context_id, "session": session}


def text_received(context_id: str, item_id: str, text: str) -> dict[str, Any]:
    """``conversation.item.input_text.received``, acknowledging an append."""
    return {
        "type": "conversation.item.input_text.received",
        "context_id": context_id,
        "item_id": item_id,
        "text": text,
    }


def audio_delta(context_id: str, item_id: str, delta: str) -> dict[str, Any]:
    """``conversation.item.audio_output.delta`` carrying base64 PCM16 for one sentence."""
    return {
        "type": "conversation.item.audio_output.delta",
        "item_id": item_id,
        "context_id": context_id,
        "delta": delta,
    }


def audio_done(context_id: str, item_id: str) -> dict[str, Any]:
    """``conversation.item.audio_output.done``, after an item's last delta."""
    return {
        "type": "conversation.item.audio_output.done",
        "item_id": item_id,
        "context_id": context_id,
    }


def context_cancelled(context_id: str) -> dict[str, Any]:
    """``context.cancelled``; no further deltas follow for that context's cancelled work."""
    return {"type": "context.cancelled", "context_id": context_id}


def tts_failed(exc: ApiError, context_id: str | None, item_id: str | None = None) -> dict[str, Any]:
    """``conversation.item.tts.failed`` with the usual ``error`` object."""
    event: dict[str, Any] = {"type": "conversation.item.tts.failed", "context_id": context_id}
    if item_id is not None:
        event["item_id"] = item_id
    event.update(error_body(exc.code, exc.message, exc.param, exc.type))
    return event
