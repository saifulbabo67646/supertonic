"""Import a voice built on a remote builder into the local library, at most once per job."""

from __future__ import annotations

from typing import Any

from supertonic_server.builder.models import Job
from supertonic_server.builder.remote_http import BuilderClient
from supertonic_server.core.errors import ApiError
from supertonic_server.voices import Voice, VoiceLibrary

REMOTE_JOB_KEY = "remote_job_id"
"""``build`` key naming the remote job a voice came from (makes the import idempotent)."""


async def fetch(
    client: BuilderClient, remote_voice_id: str, label: str, remote_job_id: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return the remote voice's style JSON and the ``build`` metadata to store locally."""
    meta = await client.voice(remote_voice_id)
    style = await client.style(remote_voice_id)
    build = meta.get("build")
    extra = {
        **(build if isinstance(build, dict) else {}),
        "builder": label,
        REMOTE_JOB_KEY: remote_job_id,
    }
    return style, extra


def already_imported(library: VoiceLibrary, label: str, remote_job_id: str) -> Voice | None:
    """The local voice imported earlier for this remote job (a crash before the job settled)."""
    for voice in library.list():
        build = voice.build or {}
        if build.get("builder") == label and build.get(REMOTE_JOB_KEY) == remote_job_id:
            return voice
    return None


def store(
    library: VoiceLibrary, job: Job, style: dict[str, Any], extra: dict[str, Any]
) -> Voice | str:
    """Import (blocking; run in a thread); return the voice, or why it could not be stored.

    A voice already imported for the same remote job is returned instead of a second copy.
    """
    existing = already_imported(library, str(extra["builder"]), str(extra[REMOTE_JOB_KEY]))
    if existing is not None:
        return existing
    req = job.request
    try:
        return library.import_style(
            style, req.name.strip(), req.description, req.tags, req.source_note, extra=extra
        )
    except (OSError, ValueError, ApiError) as exc:
        return exc.message if isinstance(exc, ApiError) else str(exc)
