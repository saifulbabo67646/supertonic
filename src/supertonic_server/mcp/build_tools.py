"""MCP tools that build a custom voice from reference audio and follow the build job."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Annotated, Any, Literal

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field

from supertonic_server.core.limits import MAX_FILES, MAX_UPLOAD_BYTES
from supertonic_server.mcp.client import SupertonicApiError, SupertonicClient
from supertonic_server.mcp.errors import fail

MIB = 1024 * 1024


def _check_files(audio_paths: list[str]) -> list[Path]:
    """Resolve the reference files, failing with the offending path before any request."""
    if not 1 <= len(audio_paths) <= MAX_FILES:
        raise ToolError(f"Provide 1 to {MAX_FILES} reference audio files, got {len(audio_paths)}")
    paths = [Path(p).expanduser().absolute() for p in audio_paths]
    total = 0
    for path in paths:
        if path.is_dir():
            raise ToolError(f"Reference audio path is not a file: {path}")
        if not path.is_file():
            raise ToolError(f"Reference audio file not found: {path}")
        total += path.stat().st_size
    if total > MAX_UPLOAD_BYTES:
        raise ToolError(
            f"Reference audio is {total / MIB:.1f} MB; the limit is "
            f"{MAX_UPLOAD_BYTES // MIB} MB in total"
        )
    return paths


def _job_view(job: dict[str, Any]) -> dict[str, Any]:
    return {k: job.get(k) for k in ("state", "progress", "voice_id", "error")}


def register_build_tools(server: MCPServer, client: SupertonicClient) -> None:
    """Add ``build_voice``, ``get_job``, ``list_jobs`` and ``finish_job`` to ``server``."""

    @server.tool()
    async def build_voice(
        audio_paths: list[str],
        name: str,
        source_note: str,
        consent: bool,
        method: Literal["accurate", "fast"] = "accurate",
        description: str = "",
        tags: list[str] | None = None,
    ) -> dict[str, str]:
        """Start building a custom voice from 1 to 3 reference recordings of one speaker.

        Requires the consent of the speaker (``consent`` must be true) and a ``source_note``
        saying whose voice it is and where the audio came from. ``accurate`` sounds much
        closer to the speaker and takes about 1.5 h on a laptop GPU; ``fast`` takes about
        15 min and is a rough likeness. The build runs in the background: call ``get_job``
        with the returned ``job_id`` to follow progress, and ``finish_job`` to stop early and
        keep the best result so far.

        Args:
            audio_paths: Paths of 1 to 3 audio files on this machine (3 to 60 s of clean
                speech in total, up to 25 MB).
            name: Display name of the new voice; not a built-in voice's name or id (``"Mia"``,
                ``"F1"``, ...).
            source_note: Whose voice this is and where the audio comes from.
            consent: True only if the speaker agreed to their voice being cloned.
            method: ``"accurate"`` (default) or ``"fast"``.
            description: Optional description.
            tags: Optional tags (no commas).

        Returns ``{job_id, state, method}``. When the job succeeds, ``get_job`` returns the
        new ``voice_id``, usable with ``speak``.
        """
        if any("," in t for t in tags or []):  # the REST form sends them comma-separated
            raise ToolError("tags cannot contain commas")
        files = await asyncio.to_thread(_check_files, audio_paths)
        try:
            job = await client.build(
                files,
                name=name,
                source_note=source_note,
                consent=consent,
                method=method,
                description=description,
                tags=tags,
            )
        except SupertonicApiError as exc:
            raise fail(exc) from exc
        return {
            "job_id": job["id"],
            "state": job["state"],
            "method": job["request"]["method"],
        }

    @server.tool()
    async def get_job(job_id: str) -> dict[str, Any]:
        """Get the state of a voice build job.

        Returns ``{state, progress, voice_id, error}``. ``state`` is ``queued``, ``running``,
        ``succeeded``, ``failed`` or ``cancelled``; ``progress`` is ``{stage, step, total,
        loss, message, at}`` or null; ``voice_id`` is set once the job succeeded; ``error`` is
        ``{code, message}`` when it failed, or when a forwarded build was cancelled while its
        builder could not be reached (``builder_unreachable``: it may still be running there).
        """
        try:
            return _job_view(await client.job(job_id))
        except SupertonicApiError as exc:
            raise fail(exc) from exc

    @server.tool()
    async def list_jobs(limit: Annotated[int, Field(ge=1, le=200)] = 10) -> list[dict[str, Any]]:
        """List recent voice build jobs, newest first.

        ``limit`` is 1 to 200. Each item is the full job:
        ``{id, state, request, progress, voice_id, error, ...}``.
        """
        try:
            return await client.jobs(limit)
        except SupertonicApiError as exc:
            raise fail(exc) from exc

    @server.tool()
    async def finish_job(job_id: str) -> dict[str, Any]:
        """End a running build's timbre stage now and keep the best result so far.

        The rhythm (speaking pace) stage still runs (2 to 5 minutes), then the voice is
        imported and the job succeeds, flagged as stopped early. Finishing while models are
        still loading makes the job fail with ``nothing_to_save``. A queued job is an error
        (``job_not_running``), as is an unknown id; a job that already ended is returned
        unchanged, and a second call while finishing changes nothing. Call ``get_job`` to
        see when it is done. Returns the updated job.
        """
        try:
            return await client.finish(job_id)
        except SupertonicApiError as exc:
            raise fail(exc) from exc
