# Adapted from supertonic.embed (src/config.yaml, `duration` section)
# https://github.com/kdrkdrkdr/supertonic.embed @ 6c38a94af2c429d7f4098708686af80d23ccadc0
# Copyright (c) 2026 Gyeongmin Kim. MIT License (see LICENSE-supertonic-embed).
"""Settings of the shared duration-style inversion (torch-free, so configs can import it)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DurationConfig:
    """supertonic.embed's ``duration`` settings (``src/config.yaml``)."""

    tolerance: float = 0.03  # converged when |rate_synth / rate_ref - 1| is under this
    max_iters: int = 8  # fixed-point budget; not a bound on the answer
    max_log_step: float = 0.6931  # ln 2: at most one octave of duration per iteration
    min_response_move: float = 0.10  # measure the model's slope only over moves this large
    saturation_move: float = 0.20  # judge saturation only past this total excursion
    saturation_slope: float = -0.2  # d log(rate) / d log(duration) above this = saturated
    invert_steps: int = 300  # Adam steps for the duration-predictor inversion
    invert_lr: float = 5.0e-3
    invert_prior: float = 1.0e-2  # pull toward the starting dp, so the answer stays plausible
