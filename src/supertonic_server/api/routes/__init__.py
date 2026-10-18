"""Route modules. Add new routers to :data:`ROUTERS` to mount them.

Authentication is not a router concern: :class:`~supertonic_server.api.guard.Guard`
protects every ``/v1/*`` path except ``GET /v1/health`` before the request is routed.
"""

from fastapi import APIRouter

from supertonic_server.api import realtime
from supertonic_server.api.routes import build, openai_speech, system, timestamps, voices

ROUTERS: list[APIRouter] = [
    system.router,
    openai_speech.router,
    build.router,
    voices.router,
    timestamps.router,
    realtime.router,
]
