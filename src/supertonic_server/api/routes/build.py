"""Voice building and job endpoints."""

from __future__ import annotations

from typing import Any, cast

from fastapi import APIRouter, Query, Request
from starlette.datastructures import UploadFile

from supertonic_server.api.deps import AppState
from supertonic_server.api.routes._common import State
from supertonic_server.builder import Builder, BuildMethod, BuildRequest
from supertonic_server.core.errors import ApiError, builder_unavailable
from supertonic_server.core.limits import MAX_FILES, MAX_UPLOAD_BYTES

router = APIRouter(prefix="/v1")

NO_BUILDER_HINT = (
    "No voice builder is available: set SUPERTONIC_BUILDER_URL or install the builder extra "
    "on a CUDA machine"
)


def _builder(state: AppState) -> Builder:
    if state.builder is None:
        raise builder_unavailable(NO_BUILDER_HINT)
    return state.builder


def _field(form: Any, name: str) -> str:
    value = form.get(name, "")
    return value if isinstance(value, str) else ""


@router.post("/voices/build", status_code=202)
async def build_voice(request: Request, state: State) -> dict[str, Any]:
    """Queue a voice build from 1-3 reference recordings (multipart); returns the job."""
    builder = _builder(state)
    form = await request.form()
    entries = form.getlist("files")
    uploads = [f for f in entries if isinstance(f, UploadFile)]
    if len(uploads) != len(entries):
        raise ApiError(
            400, "invalid_request", "files entries must be file uploads, not text", param="files"
        )
    if not 1 <= len(uploads) <= MAX_FILES:
        raise ApiError(
            400, "invalid_request", f"provide 1 to {MAX_FILES} audio files", param="files"
        )
    files: list[tuple[str, bytes]] = []
    total = 0
    for upload in uploads:
        data = await upload.read(MAX_UPLOAD_BYTES + 1 - total)
        total += len(data)
        if total > MAX_UPLOAD_BYTES:
            raise ApiError(
                413,
                "payload_too_large",
                f"Reference audio exceeds {MAX_UPLOAD_BYTES // (1024 * 1024)} MB",
                param="files",
            )
        files.append((upload.filename or "reference", data))
    req = BuildRequest(
        name=_field(form, "name"),
        description=_field(form, "description"),
        tags=[t.strip() for t in _field(form, "tags").split(",") if t.strip()],
        source_note=_field(form, "source_note"),
        consent=_field(form, "consent").strip().lower() == "true",
        # an unknown value is rejected by BuildRequest.validate (400, param method)
        method=cast(BuildMethod, _field(form, "method").strip() or "accurate"),
    )
    return (await builder.submit(req, files)).to_dict()


@router.get("/jobs")
async def list_jobs(state: State, limit: int = Query(50, ge=1, le=200)) -> dict[str, Any]:
    """List build jobs, newest first."""
    return {"data": [j.to_dict() for j in _builder(state).list(limit)]}


@router.get("/jobs/{job_id}")
async def get_job(job_id: str, state: State) -> dict[str, Any]:
    """Return one job."""
    return _builder(state).get(job_id).to_dict()


@router.delete("/jobs/{job_id}")
async def cancel_job(job_id: str, state: State) -> dict[str, Any]:
    """Cancel a queued or running job (a finished job is returned unchanged)."""
    return (await _builder(state).cancel(job_id)).to_dict()


@router.post("/jobs/{job_id}/finish")
async def finish_job(job_id: str, state: State) -> dict[str, Any]:
    """Ask a running job to stop optimising and save its best result so far."""
    return (await _builder(state).finish(job_id)).to_dict()
