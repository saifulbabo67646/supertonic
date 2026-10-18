"""System endpoints: health and languages."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends

import supertonic_server
from supertonic_server.api.deps import AppState, get_state
from supertonic_server.text import LANGUAGES

public_router = APIRouter(prefix="/v1")
router = APIRouter(prefix="/v1")

State = Annotated[AppState, Depends(get_state)]


@public_router.get("/health")
async def health(state: State) -> dict[str, Any]:
    """Liveness and basic server info; never requires auth."""
    return {
        "status": "ok",
        "model": "supertonic-3",
        "voices": len(state.library.list()),
        "builder": "none" if not state.settings.builder_url else "configured",
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
