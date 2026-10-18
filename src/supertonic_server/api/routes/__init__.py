"""Route modules. Add new routers to :data:`ROUTERS` to mount them behind the API key.

Routers in :data:`PUBLIC_ROUTERS` are mounted without the key dependency.
"""

from fastapi import APIRouter

from supertonic_server.api import realtime
from supertonic_server.api.routes import openai_speech, system, timestamps, voices

ROUTERS: list[APIRouter] = [
    system.router,
    openai_speech.router,
    voices.router,
    timestamps.router,
]
PUBLIC_ROUTERS: list[APIRouter] = [
    system.public_router,
    # The realtime socket authenticates inside its handler: an HTTP ``require_key`` failure
    # would reject the handshake without telling the client why.
    realtime.router,
]
