"""Route modules. Add new routers to :data:`ROUTERS` to mount them."""

from fastapi import APIRouter

from supertonic_server.api.routes import openai_speech, system, timestamps, voices

ROUTERS: list[APIRouter] = [
    system.router,
    openai_speech.router,
    voices.router,
    timestamps.router,
]
PUBLIC_ROUTERS: list[APIRouter] = [system.public_router]
