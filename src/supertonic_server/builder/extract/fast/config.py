# Adapted from supertonic.embed (src/config.py, src/config.yaml)
# https://github.com/kdrkdrkdr/supertonic.embed @ 6c38a94af2c429d7f4098708686af80d23ccadc0
# Copyright (c) 2026 Gyeongmin Kim. MIT License (see LICENSE-supertonic-embed).
# Adapted: config.yaml became typed dataclasses with upstream's values, except
# `batch: 1` (one speaker at a time on a 6 GB GPU, so the batch setting is gone) and the
# added `max_steps` cap (upstream descends until the threshold with no bound); model paths
# are arguments.
"""Settings of the ``fast`` method. Every tunable value lives here."""

from __future__ import annotations

from dataclasses import dataclass, field

from supertonic_server.builder.extract.common.duration import DurationConfig

WAVLM_REPO = "microsoft/wavlm-large"
WAVLM_SR = 16000  # what WavLM expects


@dataclass(frozen=True)
class ModelConfig:
    """How the frozen Supertonic is driven."""

    total_step: int = 5  # flow-matching sampling steps
    speed: float = 1.05  # Supertonic speed factor
    seed: int = 42  # fixes the noise latents, so runs repeat
    sizing_preset: str = "M1"  # whose predicted duration sets every prompt's latent length


@dataclass(frozen=True)
class TimbreConfig:
    """``style_ttl``, inverted against WavLM."""

    layer: int = 4  # WavLM-Large layer; speaker identity peaks here
    threshold: float = 0.24  # stop the moment the loss reaches this
    lr: float = 2.0e-4
    lr_patience: int = 200  # ReduceLROnPlateau
    lr_factor: float = 0.5
    grad_clip: float = 1.0
    # Not upstream: a bound on the descent so a voice that never reaches the threshold
    # still finishes (~1.7 s/step on an RTX 4050 Laptop; the R1 spike needed 181 and 319).
    max_steps: int = 1000
    progress_every: int = 10


# The five sentences the timbre objective rotates through, so a style vector cannot
# overfit one phoneme set.
PROMPTS: tuple[str, ...] = (
    "The sun sets behind the mountains, painting the sky in shades of pink and orange.",
    "Technology has transformed the way we communicate with each other around the world.",
    "She walked through the quiet forest, listening to the birds singing in the trees.",
    "Scientific research requires patience, careful observation, and rigorous analysis.",
    "The old library contained thousands of books collected over many generations.",
)


@dataclass(frozen=True)
class FastConfig:
    """All settings of the ``fast`` method."""

    model: ModelConfig = field(default_factory=ModelConfig)
    timbre: TimbreConfig = field(default_factory=TimbreConfig)
    duration: DurationConfig = field(default_factory=DurationConfig)
    prompts: tuple[str, ...] = PROMPTS
