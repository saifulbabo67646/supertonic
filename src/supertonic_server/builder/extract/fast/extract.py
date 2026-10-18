# Adapted from supertonic.embed (src/run_extract_style_batch.py)
# https://github.com/kdrkdrkdr/supertonic.embed @ 6c38a94af2c429d7f4098708686af80d23ccadc0
# Copyright (c) 2026 Gyeongmin Kim. MIT License (see LICENSE-supertonic-embed).
# Adapted: one recording per call, returning the style and a report instead of writing
# files and printing; progress and stop through callbacks; WavLM is released before the
# duration stage to save GPU memory.
"""The ``fast`` method end to end: nearest preset, timbre descent, duration inversion."""

from __future__ import annotations

import logging
from pathlib import Path

import torch

from supertonic_server.builder.extract.base import (
    NothingToSaveError,
    ProgressCallback,
    Report,
    StopCheck,
    StyleJson,
    check_stop,
    progress,
)
from supertonic_server.builder.extract.common import (
    check_readable,
    finish_with_duration,
    list_presets,
    load_frozen_tts,
    load_style,
    nearest_preset,
    preset_path,
)
from supertonic_server.builder.extract.fast.config import FastConfig
from supertonic_server.builder.extract.fast.invert_ttl import invert
from supertonic_server.builder.extract.fast.wavlm_loss import (
    load_wavlm,
    objective,
    target_from_file,
)

logger = logging.getLogger(__name__)


def extract_style(
    wav_path: Path,
    model_dir: Path,
    *,
    on_progress: ProgressCallback,
    should_stop: StopCheck,
    device: str = "cuda",
    config: FastConfig | None = None,
) -> tuple[StyleJson, Report]:
    """Build a style from ``wav_path`` with supertonic.embed's method.

    See :func:`supertonic_server.builder.extract.extract_style` for the contract.
    """
    cfg = config or FastConfig()
    dev = torch.device(device)
    check_readable(wav_path)
    presets = list_presets(model_dir)

    on_progress(progress("loading", "converting Supertonic 3 to PyTorch"))
    m = cfg.model
    tts = load_frozen_tts(
        model_dir / "onnx", dev, total_step=m.total_step, speed=m.speed, seed=m.seed
    )
    check_stop(should_stop, "while loading Supertonic")
    on_progress(progress("loading", "loading WavLM-Large"))
    wavlm = load_wavlm(dev)
    check_stop(should_stop, "while loading WavLM")
    _, sizing_dp = load_style(preset_path(model_dir, m.sizing_preset), dev)
    prompts = tts.build_prompts(cfg.prompts, sizing_dp)
    target = target_from_file(wavlm, wav_path, cfg.timbre.layer, dev)

    chosen = nearest_preset(
        presets,
        prompts[0],
        tts,
        objective(wavlm, cfg.timbre.layer, target),
        on_progress=on_progress,
        should_stop=should_stop,
    )
    if chosen is None:
        raise NothingToSaveError("stopped before any preset was measured; nothing to save")
    path, distance, preset_stopped = chosen
    logger.info("nearest preset %s at %.4f", path.stem, distance)
    ttl, dp = load_style(path, dev)

    timbre = invert(
        target,
        ttl,
        distance,
        prompts,
        tts,
        wavlm,
        cfg.timbre,
        on_progress=on_progress,
        should_stop=should_stop,
    )
    del wavlm, target
    if dev.type == "cuda":
        torch.cuda.empty_cache()

    return finish_with_duration(
        "fast",
        wav_path,
        timbre.ttl,
        dp,
        prompts,
        tts,
        cfg.duration,
        on_progress=on_progress,
        should_stop=should_stop,
        preset_start=path.stem,
        preset_distance=distance,
        loss=timbre.loss,
        steps=timbre.steps,
        stopped_early=preset_stopped or timbre.stopped,
    )
