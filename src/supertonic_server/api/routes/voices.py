"""Native voices API: list, inspect, edit, delete, import, export and preview."""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Query, Request, Response
from starlette.datastructures import UploadFile

from supertonic_server.api.deps import preview
from supertonic_server.api.routes._common import State
from supertonic_server.api.schemas import VoicePatch
from supertonic_server.core.errors import ApiError
from supertonic_server.voices import Voice

router = APIRouter(prefix="/v1")

MAX_STYLE_BYTES = 2 * 1024 * 1024
MAX_NAME_LENGTH = 100
KINDS = ("preset", "custom")


def _view(voice: Voice) -> dict[str, Any]:
    return {**voice.to_dict(), "preview_url": f"/v1/voices/{voice.id}/preview"}


def _clean_name(name: str | None) -> str:
    if name is None or not name.strip():
        raise ApiError(400, "invalid_request", "name must not be blank", param="name")
    if len(name.strip()) > MAX_NAME_LENGTH:
        raise ApiError(
            400,
            "invalid_request",
            f"name must be at most {MAX_NAME_LENGTH} characters",
            param="name",
        )
    return name.strip()


def _clean_tags(tags: list[str]) -> list[str]:
    if any(not t.strip() for t in tags):
        raise ApiError(400, "invalid_request", "tags must be non-blank strings", param="tags")
    return [t.strip() for t in tags]


def _too_large() -> ApiError:
    return ApiError(
        413,
        "payload_too_large",
        f"Style file exceeds {MAX_STYLE_BYTES // (1024 * 1024)} MB",
        param="style",
    )


def _json_dict(raw: bytes | str, param: str) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except ValueError as exc:
        raise ApiError(400, "invalid_request", f"Invalid JSON: {exc}", param=param) from exc
    if not isinstance(value, dict):
        raise ApiError(400, "invalid_request", "Expected a JSON object", param=param)
    return value


async def _read_import(request: Request) -> dict[str, Any]:
    """Normalise JSON and multipart import bodies to ``{style, name, ...}``."""
    # The guard already caps the whole body (style plus multipart framing) while it streams.
    if request.headers.get("content-type", "").startswith("multipart/"):
        form = await request.form()
        upload = form.get("file")
        if not isinstance(upload, UploadFile):
            raise ApiError(400, "invalid_request", "Missing style file", param="file")
        raw = await upload.read(MAX_STYLE_BYTES + 1)
        if len(raw) > MAX_STYLE_BYTES:
            raise _too_large()
        tags = str(form.get("tags", ""))
        return {
            "style": _json_dict(raw, "file"),
            "name": str(form.get("name", "")),
            "description": str(form.get("description", "")),
            "tags": [t.strip() for t in tags.split(",") if t.strip()],
            "source_note": str(form.get("source_note", "")),
        }
    raw = await request.body()
    if len(raw) > MAX_STYLE_BYTES:
        raise _too_large()
    return _json_dict(raw, "body")


@router.get("/voices")
async def list_voices(
    state: State, kind: str | None = None, tag: str | None = Query(None)
) -> dict[str, Any]:
    """List voices, optionally filtered by ``kind`` (preset|custom) and ``tag``."""
    if kind is not None and kind not in KINDS:
        raise ApiError(400, "invalid_request", f"kind must be one of {list(KINDS)}", param="kind")
    voices = state.library.list()
    if kind:
        voices = [v for v in voices if v.kind == kind]
    if tag:
        voices = [v for v in voices if tag in v.tags]
    return {"data": [_view(v) for v in voices]}


@router.post("/voices/import", status_code=201)
async def import_voice(request: Request, state: State) -> dict[str, Any]:
    """Import a style JSON (JSON body or multipart ``file``) as a new custom voice."""
    body = await _read_import(request)
    name = _clean_name(body.get("name"))
    raw_tags = body.get("tags") or []
    if not isinstance(raw_tags, list) or not all(isinstance(t, str) for t in raw_tags):
        raise ApiError(400, "invalid_request", "tags must be a list of strings", param="tags")
    style = body.get("style")
    if not isinstance(style, dict):
        raise ApiError(400, "invalid_style", "style must be a JSON object", param="style")
    voice = state.library.import_style(
        style,
        name,
        str(body.get("description") or ""),
        _clean_tags(raw_tags),
        str(body.get("source_note") or ""),
    )
    return _view(voice)


@router.get("/voices/{voice_id}")
async def get_voice(voice_id: str, state: State) -> dict[str, Any]:
    """Return one voice."""
    return _view(state.library.get(voice_id))


@router.patch("/voices/{voice_id}")
async def patch_voice(voice_id: str, patch: VoicePatch, state: State) -> dict[str, Any]:
    """Edit name, description or tags of a custom voice."""
    name = _clean_name(patch.name) if patch.name is not None else None
    tags = _clean_tags(patch.tags) if patch.tags is not None else None
    voice = state.library.update(voice_id, name=name, description=patch.description, tags=tags)
    return _view(voice)


@router.delete("/voices/{voice_id}", status_code=204)
async def delete_voice(voice_id: str, state: State) -> Response:
    """Delete a custom voice."""
    state.library.delete(voice_id)
    return Response(status_code=204)


@router.get("/voices/{voice_id}/style")
async def export_style(voice_id: str, state: State) -> Response:
    """Download the voice's style JSON."""
    voice = state.library.get(voice_id)
    body = json.dumps(state.library.style_json(voice.id))
    return Response(
        body,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{voice.id}.json"'},
    )


@router.get("/voices/{voice_id}/preview")
async def voice_preview(voice_id: str, state: State, language: str = "en") -> Response:
    """Return the cached sample WAV for a voice in ``language``."""
    path = await preview(state, voice_id, language)
    return Response(path.read_bytes(), media_type="audio/wav")
