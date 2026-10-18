"""Realtime TTS over WebSocket (``/v1/audio/speech/websocket``)."""

from supertonic_server.api.realtime.endpoint import router
from supertonic_server.api.realtime.session import Session

__all__ = ["Session", "router"]
