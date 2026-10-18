# Adapted from supertonic3-voice-clone (train_style.py, `main`)
# https://github.com/saurabhv749/supertonic3-voice-clone @ 765ce5e27daa8d30937e2d0d8f9730280add5748
# Copyright (c) 2026 Saurabh Verma. MIT License (see LICENSE-supertonic3-voice-clone).
# train_style.py is a modified optimize_style.py by Gyeongmin Kim
# (https://github.com/kdrkdrkdr), MIT License.
# Adapted: one recording per call, returning the style and a report instead of writing
# files and printing; the start preset is always the nearest by speaker loss (upstream's
# `--reference-style auto`); style_dp comes from supertonic.embed's duration inversion
# instead of staying at the preset's; progress and stop through callbacks; ECAPA is
# released before the duration stage to save GPU memory.
"""The ``accurate`` method end to end: nearest preset, ECAPA descent, duration inversion."""

from __future__ import annotations

import logging
from pathlib import Path

import torch

from supertonic_server.builder.extract.accurate.config import AccurateConfig, config_from_env
from supertonic_server.builder.extract.accurate.optimize import (
    nearest_preset,
    optimise,
    training_prompts,
)
from supertonic_server.builder.extract.accurate.speaker_loss import (
    SpeakerLoss,
    load_ecapa,
    load_reference16,
)
from supertonic_server.builder.extract.accurate.utterances import texts as TRAINING_TEXTS
from supertonic_server.builder.extract.base import (
    NothingToSaveError,
    ProgressCallback,
    Report,
    StopCheck,
    StyleJson,
    check_stop,
    make_report,
    progress,
)
from supertonic_server.builder.extract.common import (
    check_readable,
    duration_inversion,
    list_presets,
    load_frozen_tts,
    load_mono,
    load_style,
    preset_path,
    style_to_json,
)
from supertonic_server.builder.extract.common.duration import RATE_SR

logger = logging.getLogger(__name__)


def extract_style(
    wav_path: Path,
    model_dir: Path,
    *,
    on_progress: ProgressCallback,
    should_stop: StopCheck,
    device: str = "cuda",
    config: AccurateConfig | None = None,
) -> tuple[StyleJson, Report]:
    """Build a style from ``wav_path`` with supertonic3-voice-clone's method.

    ``config`` defaults to :func:`config_from_env` (``SUPERTONIC_BUILDER_ACCURATE_STEPS``
    overrides the step count). See :func:`supertonic_server.builder.extract.extract_style`
    for the contract; the report adds ``similarity`` (= 1 - loss) and ``best_step``.
    """
    cfg = config or config_from_env()
    dev = torch.device(device)
    check_readable(wav_path)
    presets = list_presets(model_dir)

    on_progress(progress("loading", "converting Supertonic 3 to PyTorch"))
    tts = load_frozen_tts(
        model_dir / "onnx", dev, total_step=cfg.vocoder_steps, speed=cfg.speed, seed=cfg.seed
    )
    check_stop(should_stop, "while loading Supertonic")
    on_progress(progress("loading", "loading the ECAPA speaker encoder"))
    encoder = load_ecapa(dev)
    check_stop(should_stop, "while loading ECAPA")
    loss_fn = SpeakerLoss(encoder, load_reference16(wav_path, dev), dev)
    _, sizing_dp = load_style(preset_path(model_dir, cfg.sizing_preset), dev)
    prompts = training_prompts(tts, TRAINING_TEXTS, sizing_dp, cfg.seed)

    chosen = nearest_preset(
        presets, prompts[0], tts, loss_fn, on_progress=on_progress, should_stop=should_stop
    )
    if chosen is None:
        raise NothingToSaveError("stopped before any preset was measured; nothing to save")
    path, preset_loss, preset_stopped = chosen
    logger.info("nearest preset %s at %.4f", path.stem, preset_loss)
    ttl, dp = load_style(path, dev)

    timbre = optimise(
        ttl,
        preset_loss,
        prompts,
        tts,
        loss_fn,
        cfg,
        on_progress=on_progress,
        should_stop=should_stop,
    )
    del loss_fn, encoder, prompts
    if dev.type == "cuda":
        torch.cuda.empty_cache()

    on_progress(
        progress(
            "duration", "matching the reference speaking rate", step=0, total=cfg.duration.max_iters
        )
    )
    duration_prompts = tts.build_prompts(cfg.duration_prompts, dp)
    dp, duration = duration_inversion(
        load_mono(wav_path, RATE_SR),
        timbre.ttl,
        dp,
        duration_prompts,
        tts,
        cfg.duration,
        on_progress=on_progress,
        should_stop=should_stop,
    )
    report = make_report(
        "accurate",
        preset_start=path.stem,
        preset_distance=preset_loss,
        loss=timbre.loss,
        steps=timbre.taken,
        duration=duration,
        stopped_early=preset_stopped or timbre.stopped,
        similarity=round(1 - timbre.loss, 4),
        best_step=timbre.best_step,
    )
    return style_to_json(timbre.ttl, dp, source=Path(wav_path).name), report
