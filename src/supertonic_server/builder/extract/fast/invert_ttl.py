# Adapted from supertonic.embed (src/invert_ttl.py)
# https://github.com/kdrkdrkdr/supertonic.embed @ 6c38a94af2c429d7f4098708686af80d23ccadc0
# Copyright (c) 2026 Gyeongmin Kim. MIT License (see LICENSE-supertonic-embed).
# Adapted: one speaker at a time (`batch: 1`), so the batch queue is gone; a `max_steps`
# bound; progress through a callback every `progress_every` steps; a stop check polled
# every step that keeps the best vector so far; the nearest-preset scan reports each
# preset and can be stopped; typed. The descent itself is unchanged.
"""Recover the timbre style by gradient descent on the WavLM objective.

Start at the nearest shipped preset, descend, and after every step put all 50 rows back
on the unit sphere. Stop the moment the loss reaches the threshold.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import torch

from supertonic_server.builder.extract.base import ProgressCallback, StopCheck, progress
from supertonic_server.builder.extract.common.frozen_tts import FrozenTTS, Prompt
from supertonic_server.builder.extract.common.style_file import load_style, project_to_sphere
from supertonic_server.builder.extract.fast.config import TimbreConfig
from supertonic_server.builder.extract.fast.wavlm_loss import (
    Stats,
    layer_stats,
    style_loss,
    to_wavlm_rate,
)


@dataclass
class TimbreResult:
    """The best ``style_ttl`` found, its loss and the step that reached it."""

    ttl: torch.Tensor
    loss: float
    steps: int  # steps to the best loss
    taken: int  # steps run
    stopped: bool  # ended by the stop check


def nearest_preset(
    target: Stats,
    presets: Sequence[Path],
    prompt: Prompt,
    tts: FrozenTTS,
    wavlm: Any,
    layer: int,
    *,
    on_progress: ProgressCallback,
    should_stop: StopCheck,
) -> tuple[Path, float, bool] | None:
    """``(preset, distance, stopped)`` of the closest preset under the objective.

    ``None`` when stopped before any preset was measured.
    """
    best: tuple[Path, float] | None = None
    for i, path in enumerate(presets, 1):
        if should_stop():
            return None if best is None else (*best, True)
        ttl, _ = load_style(path, tts.device)
        wav = tts.synthesize(prompt, ttl)
        with torch.no_grad():
            distance = style_loss(layer_stats(wavlm, to_wavlm_rate(wav), layer), target).item()
        if best is None or distance < best[1]:
            best = (path, distance)
        on_progress(
            progress(
                "preset", f"{path.stem}: {distance:.4f}", step=i, total=len(presets), loss=distance
            )
        )
    return None if best is None else (*best, False)


def invert(
    target: Stats,
    ttl_start: torch.Tensor,
    start_loss: float,
    prompts: Sequence[Prompt],
    tts: FrozenTTS,
    wavlm: Any,
    cfg: TimbreConfig,
    *,
    on_progress: ProgressCallback,
    should_stop: StopCheck,
) -> TimbreResult:
    """Descend from ``ttl_start`` (whose loss is ``start_loss``) toward ``target``."""
    ttl = ttl_start.clone().requires_grad_(True)
    optimizer = torch.optim.Adam([ttl], lr=cfg.lr)
    schedule = torch.optim.lr_scheduler.ReduceLROnPlateau(
        optimizer, patience=cfg.lr_patience, factor=cfg.lr_factor, min_lr=cfg.lr * 0.01
    )
    best_ttl, best_loss, best_step = ttl_start.detach().clone(), start_loss, 0
    taken, stopped = 0, False

    while taken < cfg.max_steps and best_loss > cfg.threshold:
        if should_stop():
            stopped = True
            break
        # one prompt per step, rotating so the vector cannot overfit one sentence
        prompt = prompts[taken % len(prompts)]
        wav = tts.forward(prompt.ids, prompt.mask, ttl, prompt.latent, prompt.latent_mask)
        loss = style_loss(layer_stats(wavlm, to_wavlm_rate(wav), cfg.layer), target)
        optimizer.zero_grad()
        loss.backward()  # type: ignore[no-untyped-call]
        value = loss.item()
        taken += 1
        if value < best_loss:
            # the loss was measured on the projected vector from the previous step, so
            # keep a projected clone rather than the half-stepped one
            best_ttl, best_loss, best_step = ttl.detach().clone(), value, taken
            with torch.no_grad():
                project_to_sphere(best_ttl)
        torch.nn.utils.clip_grad_norm_([ttl], cfg.grad_clip)
        optimizer.step()
        with torch.no_grad():
            project_to_sphere(ttl.data)
        schedule.step(value)
        if taken % cfg.progress_every == 0:
            on_progress(
                progress(
                    "timbre",
                    f"step {taken}: loss {value:.4f} (best {best_loss:.4f})",
                    step=taken,
                    total=cfg.max_steps,
                    loss=best_loss,
                )
            )
    if taken % cfg.progress_every != 0:
        on_progress(
            progress(
                "timbre",
                f"timbre done after {taken} steps: best loss {best_loss:.4f}",
                step=taken,
                total=cfg.max_steps,
                loss=best_loss,
            )
        )
    return TimbreResult(best_ttl, best_loss, best_step, taken, stopped)
