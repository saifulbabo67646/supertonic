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
    progress,
)
from supertonic_server.builder.extract.common import (
    duration_inversion,
    list_presets,
    load_frozen_tts,
    load_mono,
    load_style,
    preset_path,
    style_to_json,
)
from supertonic_server.builder.extract.fast.config import WAVLM_SR, FastConfig
from supertonic_server.builder.extract.fast.invert_ttl import invert, nearest_preset
from supertonic_server.builder.extract.fast.wavlm_loss import load_wavlm, target_from_file

logger = logging.getLogger(__name__)


def _check_stop(should_stop: StopCheck) -> None:
    if should_stop():
        raise NothingToSaveError("stopped before a starting voice was chosen; nothing to save")


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
    presets = list_presets(model_dir)

    on_progress(progress("loading", "converting Supertonic 3 to PyTorch"))
    m = cfg.model
    tts = load_frozen_tts(
        model_dir / "onnx", dev, total_step=m.total_step, speed=m.speed, seed=m.seed
    )
    _check_stop(should_stop)
    on_progress(progress("loading", "loading WavLM-Large"))
    wavlm = load_wavlm(dev)
    _check_stop(should_stop)
    _, sizing_dp = load_style(preset_path(model_dir, m.sizing_preset), dev)
    prompts = tts.build_prompts(cfg.prompts, sizing_dp)
    target = target_from_file(wavlm, wav_path, cfg.timbre.layer, dev)

    chosen = nearest_preset(
        target,
        presets,
        prompts[0],
        tts,
        wavlm,
        cfg.timbre.layer,
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

    on_progress(
        progress(
            "duration", "matching the reference speaking rate", step=0, total=cfg.duration.max_iters
        )
    )
    reference16 = load_mono(wav_path, WAVLM_SR)
    dp, duration = duration_inversion(
        reference16,
        timbre.ttl,
        dp,
        prompts,
        tts,
        cfg.duration,
        on_progress=on_progress,
        should_stop=should_stop,
    )
    stopped = preset_stopped or timbre.stopped or duration["status"] == "stopped"
    report: Report = {
        "method": "fast",
        "preset_start": path.stem,
        "preset_distance": round(distance, 4),
        "loss": round(timbre.loss, 4),
        "steps": timbre.steps,
        "duration_status": duration["status"],
        "rate_ref": duration.get("rate_ref"),
        "rate_final": duration.get("rate_final"),
        "stopped_early": stopped,
    }
    return style_to_json(timbre.ttl, dp, source=Path(wav_path).name), report
