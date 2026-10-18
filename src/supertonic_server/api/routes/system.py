"""System endpoints: health and languages."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

import supertonic_server
from supertonic_server.api.routes._common import State
from supertonic_server.text import LANGUAGES

router = APIRouter(prefix="/v1")


@router.get("/health")
async def health(state: State) -> dict[str, Any]:
    """Liveness and basic server info; ``GET`` never requires auth (see the guard)."""
    builder = state.builder
    return {
        "status": "ok",
        "model": "supertonic-3",
        "voices": len(state.library.list()),
        "builder": "none" if builder is None else builder.kind,
        "builder_detail": None if builder is None else builder.detail(),
        "auth": bool(state.settings.api_key),
        "version": supertonic_server.__version__,
    }


@router.get("/languages")
async def languages() -> dict[str, Any]:
    """List supported languages with a sample sentence each."""
    return {
        "data": [
            {"code": lang.code, "name": lang.name, "sample": lang.sample, "spaced": lang.spaced}
            for lang in LANGUAGES
        ]
    }
