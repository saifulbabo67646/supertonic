"""Realtime TTS over WebSocket (``/v1/audio/speech/websocket``)."""

from supertonic_server.api.realtime.session import Session, router

__all__ = ["Session", "router"]
