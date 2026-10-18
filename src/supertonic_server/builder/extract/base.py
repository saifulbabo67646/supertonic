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


def check_stop(should_stop: StopCheck, when: str) -> None:
    """Raise :class:`NothingToSaveError` if a stop is requested before any style exists.

    Args:
        should_stop: The stop check.
        when: What was happening, for the message (e.g. ``"while loading models"``).
    """
    if should_stop():
        raise NothingToSaveError(f"stopped {when}, before any style existed; nothing to save")


def make_report(
    method: str,
    *,
    preset_start: str,
    preset_distance: float,
    loss: float,
    steps: int,
    duration: dict[str, Any],
    stopped_early: bool,
    **extra: Any,
) -> Report:
    """The report every method returns (``extra`` adds method-specific keys).

    ``duration`` is the report of the shared duration inversion; a ``"stopped"`` status
    also counts as stopping early.
    """
    return {
        "method": method,
        "preset_start": preset_start,
        "preset_distance": round(preset_distance, 4),
        "loss": round(loss, 4),
        "steps": steps,
        "duration_status": duration["status"],
        "rate_ref": duration.get("rate_ref"),
        "rate_final": duration.get("rate_final"),
        "stopped_early": stopped_early or duration["status"] == "stopped",
        **extra,
    }
