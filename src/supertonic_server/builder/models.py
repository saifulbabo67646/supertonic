"""Data models for voice-building jobs (no heavy imports; safe for the server process)."""

from __future__ import annotations

import builtins
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from typing import Any, Literal, Protocol, get_args

from supertonic_server.core.errors import ApiError

JobState = Literal["queued", "running", "succeeded", "failed", "cancelled"]
BuildMethod = Literal["accurate", "fast"]
Stage = Literal["preparing", "loading", "preset", "timbre", "duration", "saving"]

BUILD_METHODS: tuple[BuildMethod, ...] = ("accurate", "fast")
MAX_NAME_LEN = 100


@dataclass
class BuildRequest:
    """What the user asked to build, with the provenance and consent that must accompany it."""

    name: str
    description: str
    tags: list[str]
    source_note: str
    consent: bool
    method: BuildMethod = "accurate"

    def validate(self) -> None:
        """Raise ``ApiError`` (400) when the request is unusable."""
        name = self.name.strip()
        if not name or len(name) > MAX_NAME_LEN:
            raise ApiError(
                400, "invalid_request", f"name must be 1-{MAX_NAME_LEN} characters", param="name"
            )
        if self.method not in BUILD_METHODS:
            raise ApiError(
                400,
                "invalid_request",
                f"method must be one of: {', '.join(BUILD_METHODS)}",
                param="method",
            )
        if not self.source_note.strip():
            raise ApiError(400, "consent_required", "source_note is required", param="source_note")
        if self.consent is not True:
            raise ApiError(
                400,
                "consent_required",
                "consent must be true: confirm you have the right to clone this voice",
                param="consent",
            )


@dataclass
class Progress:
    """A snapshot of how far a build has got."""

    stage: Stage
    step: int | None
    total: int | None
    loss: float | None
    message: str
    at: str


@dataclass
class Job:
    """A voice-building job and its lifecycle state."""

    id: str
    state: JobState
    request: BuildRequest
    created_at: str
    started_at: str | None
    finished_at: str | None
    progress: Progress | None
    voice_id: str | None
    error: dict[str, Any] | None
    builder: str
    stopping: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable dict."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Job:
        """Rebuild a job from ``to_dict`` output; a missing ``method`` means ``accurate``."""
        req = {"method": "accurate", **data["request"]}
        progress = data.get("progress")
        known = set(get_args(Stage))
        if progress is not None and progress["stage"] not in known:
            raise ValueError(f"unknown progress stage: {progress['stage']!r}")
        return cls(
            id=data["id"],
            state=data["state"],
            request=BuildRequest(**req),
            created_at=data["created_at"],
            started_at=data.get("started_at"),
            finished_at=data.get("finished_at"),
            progress=Progress(**progress) if progress is not None else None,
            voice_id=data.get("voice_id"),
            error=data.get("error"),
            builder=data["builder"],
            stopping=bool(data.get("stopping", False)),
        )


class Builder(Protocol):
    """What the API needs from a voice builder (a local ``JobManager`` or a remote forwarder)."""

    @property
    def methods(self) -> tuple[BuildMethod, ...]:
        """Build methods this builder can run."""
        ...

    async def start(self) -> None:
        """Get ready to accept builds."""
        ...

    async def close(self) -> None:
        """Stop accepting builds and release resources."""
        ...

    async def submit(
        self, req: BuildRequest, files: Sequence[tuple[str, bytes]], builder_label: str = "local"
    ) -> Job:
        """Validate and queue a build."""
        ...

    def get(self, job_id: str) -> Job:
        """Return a job or raise 404 ``job_not_found``."""
        ...

    def list(self, limit: int = 50) -> builtins.list[Job]:
        """Most recent jobs first."""
        ...

    async def cancel(self, job_id: str) -> Job:
        """Cancel a queued or running job."""
        ...

    async def finish(self, job_id: str) -> Job:
        """Ask a running job to save its best result now."""
        ...
