"""A torch-free stand-in extractor, selected by the worker when ``SUPERTONIC_BUILDER_FAKE=1``.

It emits three progress events (``loading``, ``timbre``, ``duration``) and returns a random
style with unit rows. When the stop check is true it returns right after the current event
with ``stopped_early: true``. A missing ``wav_path`` raises ``FileNotFoundError``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from supertonic_server.builder.extract.base import (
    ProgressCallback,
    Report,
    StopCheck,
    StyleJson,
    progress,
)
from supertonic_server.builder.models import BUILD_METHODS, BuildMethod

FAKE_STEPS = 3


def _unit_rows(rng: np.random.Generator, dims: list[int]) -> dict[str, object]:
    arr = rng.standard_normal(dims).astype(np.float32)
    arr /= np.linalg.norm(arr, axis=-1, keepdims=True)
    return {"data": arr.tolist(), "dims": dims, "type": "float32"}


def make_style(seed: int = 0, source: str = "fake") -> StyleJson:
    """A valid Supertonic 3 style document with unit-norm rows."""
    rng = np.random.default_rng(seed)
    return {
        "style_ttl": _unit_rows(rng, [1, 50, 256]),
        "style_dp": _unit_rows(rng, [1, 8, 16]),
        "metadata": {"source_file": source, "extracted_at": datetime.now(UTC).isoformat()},
    }


def extract_style(
    method: BuildMethod,
    wav_path: Path,
    model_dir: Path,
    *,
    on_progress: ProgressCallback,
    should_stop: StopCheck,
    device: str = "cuda",
) -> tuple[StyleJson, Report]:
    """Pretend to build a style; same contract as :func:`..extract.extract_style`."""
    if method not in BUILD_METHODS:
        raise ValueError(f"unknown build method {method!r}")
    if not Path(wav_path).exists():
        raise FileNotFoundError(f"reference recording not found: {wav_path}")
    events = [
        progress("loading", "fake: loading"),
        progress("timbre", "fake: timbre", step=1, total=FAKE_STEPS, loss=0.5),
        progress("duration", "fake: duration", step=1, total=1),
    ]
    stopped = False
    for event in events:
        on_progress(event)
        if should_stop():
            stopped = True
            break
    report: Report = {
        "method": method,
        "preset_start": "F1",
        "preset_distance": 0.5,
        "loss": 0.5,
        "steps": 1 if stopped else FAKE_STEPS,
        "duration_status": "stopped" if stopped else "converged",
        "rate_ref": 3.0,
        "rate_final": 3.0,
        "stopped_early": stopped,
    }
    return make_style(source=Path(wav_path).name), report
