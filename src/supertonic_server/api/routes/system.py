"""System endpoints: health and languages."""

from __future__ import annotations

import hmac
from typing import Any

from fastapi import APIRouter, Request

import supertonic_server
from supertonic_server.api.guard import bearer_token
from supertonic_server.api.routes._common import State
from supertonic_server.text import LANGUAGES

router = APIRouter(prefix="/v1")

PRIVATE_DETAIL = ("host", "device")
"""``builder_detail`` keys shown only to callers with the key: the builder's network
address and the GPU name."""


def _may_see_private(request: Request, api_key: str | None) -> bool:
    if not api_key:
        return True
    return hmac.compare_digest(bearer_token(request.headers).encode(), api_key.encode())


@router.get("/health")
async def health(state: State, request: Request) -> dict[str, Any]:
    """Liveness and basic server info; ``GET`` never requires auth (see the guard).

    With an API key set, ``builder_detail`` leaves out the builder host and the GPU name
    unless the request carries the key.
    """
    builder = state.builder
    detail = None if builder is None else builder.detail()
    if detail is not None and not _may_see_private(request, state.settings.api_key):
        detail = {k: v for k, v in detail.items() if k not in PRIVATE_DETAIL}
    return {
        "status": "ok",
        "model": "supertonic-3",
        "voices": len(state.library.list()),
        "builder": "none" if builder is None else builder.kind,
        "builder_detail": detail,
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
