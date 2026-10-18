"""Route modules. Add new routers to :data:`ROUTERS` to mount them."""

from fastapi import APIRouter

from supertonic_server.api.routes import openai_speech, system

ROUTERS: list[APIRouter] = [system.router, openai_speech.router]
PUBLIC_ROUTERS: list[APIRouter] = [system.public_router]
