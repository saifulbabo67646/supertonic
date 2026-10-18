# Adapted from supertonic.embed (src/run_extract_style_batch.py, the duration stage)
# https://github.com/kdrkdrkdr/supertonic.embed @ 6c38a94af2c429d7f4098708686af80d23ccadc0
# Copyright (c) 2026 Gyeongmin Kim. MIT License (see LICENSE-supertonic-embed).
# Adapted: shared by both methods; returns the style and the report instead of writing
# files; progress and stop through callbacks; typed.
"""The tail every method shares: duration inversion, then the style and its report."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

import torch

from supertonic_server.builder.extract.base import (
    ProgressCallback,
    Report,
    StopCheck,
    StyleJson,
    make_report,
    progress,
)
from supertonic_server.builder.extract.common.audio import load_mono
from supertonic_server.builder.extract.common.duration import RATE_SR, duration_inversion
from supertonic_server.builder.extract.common.frozen_tts import FrozenTTS, Prompt
from supertonic_server.builder.extract.common.style_file import style_to_json
from supertonic_server.builder.extract.duration_config import DurationConfig


def finish_with_duration(
    method: str,
    wav_path: Path,
    ttl: torch.Tensor,
    dp_start: torch.Tensor,
    prompts: Sequence[Prompt],
    tts: FrozenTTS,
    cfg: DurationConfig,
    *,
    on_progress: ProgressCallback,
    should_stop: StopCheck,
    preset_start: str,
    preset_distance: float,
    loss: float,
    steps: int,
    stopped_early: bool,
    **extra: Any,
) -> tuple[StyleJson, Report]:
    """Invert ``style_dp`` from ``dp_start`` against the reference rate, then build the result.

    ``prompts`` are the sentences the speaking rate is measured on; ``extra`` adds
    method-specific report keys (see :func:`~supertonic_server.builder.extract.base.make_report`).

    Finish now ends only the timbre stage: when the stop was already requested on entry, the
    rhythm match still runs in full (the stop file stays in place, so it would otherwise end
    this stage at once). A stop that first arrives during this stage ends it early.
    """
    rhythm_stop: StopCheck = (lambda: False) if should_stop() else should_stop
    on_progress(
        progress("duration", "matching the reference speaking rate", step=0, total=cfg.max_iters)
    )
    dp, duration = duration_inversion(
        load_mono(wav_path, RATE_SR),
        ttl,
        dp_start,
        prompts,
        tts,
        cfg,
        on_progress=on_progress,
        should_stop=rhythm_stop,
    )
    report = make_report(
        method,
        preset_start=preset_start,
        preset_distance=preset_distance,
        loss=loss,
        steps=steps,
        duration=duration,
        stopped_early=stopped_early,
        **extra,
    )
    return style_to_json(ttl, dp, source=Path(wav_path).name), report
