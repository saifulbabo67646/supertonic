"""Types shared by every extractor (no heavy imports; safe anywhere)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from supertonic_server.builder.models import Progress, Stage

ProgressCallback = Callable[[Progress], None]
StopCheck = Callable[[], bool]
StyleJson = dict[str, Any]
Report = dict[str, Any]


class NothingToSaveError(RuntimeError):
    """A stop was requested before any style existed to save."""


def progress(
    stage: Stage,
    message: str,
    *,
    step: int | None = None,
    total: int | None = None,
    loss: float | None = None,
) -> Progress:
    """Build a :class:`Progress` stamped with the current UTC time."""
    return Progress(
        stage=stage,
        step=step,
        total=total,
        loss=loss,
        message=message,
        at=datetime.now(UTC).isoformat(),
    )
