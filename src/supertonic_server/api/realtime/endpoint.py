"""The realtime WebSocket route: connection checks, then a :class:`~.session.Session`.

Authentication: send ``Authorization: Bearer <key>`` when the client can set headers. The
``?api_key=`` query parameter exists for browsers, whose WebSocket API cannot set headers;
query strings tend to end up in proxy and access logs (the CLI redacts it from uvicorn's
access log), so prefer the header.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from fastapi import APIRouter, WebSocket
from starlette.websockets import WebSocketDisconnect

from supertonic_server.api.guard import WS_REJECTION
from supertonic_server.api.realtime import protocol as p
from supertonic_server.api.realtime.params import parse_params
from supertonic_server.api.realtime.session import Session
from supertonic_server.core.errors import ApiError

if TYPE_CHECKING:
    from supertonic_server.api.deps import AppState

logger = logging.getLogger(__name__)

router = APIRouter()

_POLICY_VIOLATION = 1008
_TRY_AGAIN_LATER = 1013


@router.websocket("/v1/audio/speech/websocket")
async def speech_websocket(ws: WebSocket) -> None:
    """Realtime TTS: text streamed in, base64 PCM16 sentences streamed out.

    The guard checks the key (``Authorization: Bearer`` or ``?api_key=``) and leaves any
    rejection in the scope; the socket is accepted first so the client gets a
    ``conversation.item.tts.failed`` event explaining the rejection before the 1008 close.
    """
    await ws.accept()
    rejection: ApiError | None = ws.scope.get(WS_REJECTION)
    if rejection is not None:  # set by the guard: bad key, or forwarded without a key
        await _reject(ws, rejection, _POLICY_VIOLATION)
        return
    state: AppState | None = getattr(ws.app.state, "app_state", None)
    if state is None:
        exc = ApiError(503, "not_ready", "Model is still loading", type_="server_error")
        await _reject(ws, exc, _TRY_AGAIN_LATER)
        return
    try:
        params = parse_params(ws.query_params, state)
    except ApiError as exc:
        await _reject(ws, exc, _POLICY_VIOLATION)
        return
    await Session(ws, state, params).run()


async def _reject(ws: WebSocket, exc: ApiError, close_code: int) -> None:
    """Explain a refused connection, then close it (quietly if the client already left)."""
    try:
        await ws.send_json(p.tts_failed(exc, None))
        await ws.close(close_code)
    except (WebSocketDisconnect, RuntimeError, OSError) as err:
        logger.debug("realtime client left during rejection: %r", err)
