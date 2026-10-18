# Adapted from supertonic3-voice-clone (train_style.py, `build_parser` defaults)
# https://github.com/saurabhv749/supertonic3-voice-clone @ 765ce5e27daa8d30937e2d0d8f9730280add5748
# Copyright (c) 2026 Saurabh Verma. MIT License (see LICENSE-supertonic3-voice-clone).
# train_style.py is itself a modified optimize_style.py by Gyeongmin Kim (MIT).
# Adapted: argparse defaults became a typed dataclass with upstream's values; checkpoint
# saving (`save_steps`) is gone; the F4 sizing preset (upstream's female default) is fixed;
# the duration inversion settings are added (upstream leaves style_dp at the preset's).
"""Settings of the ``accurate`` method (torch-free). Every tunable value lives here."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field, replace

from supertonic_server.builder.extract.duration_config import DurationConfig
from supertonic_server.builder.extract.fast.config import PROMPTS as EMBED_PROMPTS

ECAPA_SOURCE = "speechbrain/spkrec-ecapa-voxceleb"
ECAPA_SR = 16000  # what ECAPA expects
ECAPA_SAVEDIR_NAME = "supertonic-ecapa"  # under the Hugging Face hub cache
STEPS_ENV = "SUPERTONIC_BUILDER_ACCURATE_STEPS"  # debugging knob: overrides num_steps


@dataclass(frozen=True)
class AccurateConfig:
    """All settings of the ``accurate`` method (upstream's ``train_style.py`` defaults)."""

    lr: float = 2.0e-4  # Adam on style_ttl only
    lr_patience: int = 200  # ReduceLROnPlateau, stepped on the loss every step
    lr_factor: float = 0.5
    min_lr: float = 2.0e-6  # lr * 0.01
    grad_clip: float = 1.0
    num_steps: int = 3000
    threshold: float = 0.015  # early stop once the best loss is at or below this
    vocoder_steps: int = 6  # flow-matching steps per synthesis
    speed: float = 1.05
    seed: int = 49  # fixes the noisy latent
    sizing_preset: str = "F4"  # whose duration on the first text sizes the fixed latent
    log_every: int = 8
    duration: DurationConfig = field(default_factory=DurationConfig)
    # The duration inversion runs over supertonic.embed's sentences, as in ``fast``.
    duration_prompts: tuple[str, ...] = EMBED_PROMPTS


def config_from_env(environ: Mapping[str, str] | None = None) -> AccurateConfig:
    """The default config, with ``num_steps`` from :data:`STEPS_ENV` when it is set.

    Raises:
        ValueError: the variable is set but is not a positive integer.
    """
    env = os.environ if environ is None else environ
    raw = env.get(STEPS_ENV)
    cfg = AccurateConfig()
    if raw is None:
        return cfg
    try:
        steps = int(raw.strip())
    except ValueError:
        steps = 0
    if steps < 1:
        raise ValueError(f"{STEPS_ENV} must be a positive integer, got {raw!r}")
    return replace(cfg, num_steps=steps)
