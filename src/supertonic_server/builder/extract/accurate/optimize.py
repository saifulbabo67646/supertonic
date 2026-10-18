# Adapted from supertonic3-voice-clone (train_style.py, utils/dataloader.py)
# https://github.com/saurabhv749/supertonic3-voice-clone @ 765ce5e27daa8d30937e2d0d8f9730280add5748
# Copyright (c) 2026 Saurabh Verma. MIT License (see LICENSE-supertonic3-voice-clone).
# train_style.py is a modified optimize_style.py by Gyeongmin Kim
# (https://github.com/kdrkdrkdr), MIT License.
# Adapted: the script became two functions (the preset scan is shared, in
# common/preset_scan.py); the DataLoader became a list of prompts
# tokenised in one padded batch by the `supertonic` package's text processor and sorted
# longest first, as upstream does; the loss is an argument; progress through a callback
# and a stop check polled every step that keeps the best vector so far; the best vector is
# the one that produced the best loss (upstream cloned it after the optimiser step);
# checkpoint files are gone; typed. Hyper-parameters and the loop are unchanged.
"""The ``accurate`` descent: Adam on ``style_ttl`` against the speaker loss.

One noisy latent is drawn once (seeded), sized from the sizing preset's duration on the
first (longest) sentence, and every synthesis uses it, so only the style changes between
steps. The preset scan (shared) measures every preset on that first sentence; the descent
then rotates through the sentences one per step, starting with the second.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
import torch

from supertonic_server.builder.extract.accurate.config import AccurateConfig
from supertonic_server.builder.extract.base import ProgressCallback, StopCheck, progress
from supertonic_server.builder.extract.common.frozen_tts import SR, FrozenTTS, Prompt
from supertonic_server.builder.extract.common.preset_scan import WaveLoss


@dataclass
class TimbreResult:
    """The best ``style_ttl`` found and how the descent went."""

    ttl: torch.Tensor
    loss: float  # best loss
    best_step: int  # step that measured it (0: none taken, the start vector)
    taken: int  # steps run
    stopped: bool  # ended by the stop check


def training_prompts(
    tts: FrozenTTS, texts: Sequence[Sequence[str]], sizing_dp: torch.Tensor, seed: int
) -> list[Prompt]:
    """The ``[lang, text]`` sentences as prompts, longest first, sharing one fixed latent.

    Raises:
        ValueError: the sentences are not all in one language.
    """
    langs = {lang for lang, _ in texts}
    if len(langs) != 1:
        raise ValueError(f"training texts must share one language, got {sorted(langs)}")
    ids_np, mask_np = tts.text([text for _, text in texts], langs.pop())
    lengths = mask_np.reshape(len(texts), -1).sum(axis=1)
    order = sorted(range(len(texts)), key=lambda i: -int(lengths[i]))  # stable
    ids = torch.tensor(ids_np[order], dtype=torch.int64, device=tts.device)
    mask = torch.tensor(mask_np[order], dtype=torch.float32, device=tts.device)

    torch.manual_seed(seed)
    with torch.no_grad():
        seconds = float(tts.seconds(ids[:1], mask[:1], sizing_dp).reshape(()))
    # upstream's sample_noisy_latent: ceil on the (float) sample count
    frames = int((seconds * SR + tts.chunk - 1) / tts.chunk)
    noise = np.random.RandomState(seed).randn(1, tts.latent_dim, frames).astype(np.float32)
    latent = torch.tensor(noise, device=tts.device)
    latent_mask = torch.ones(1, 1, frames, device=tts.device)
    return [
        Prompt(ids=ids[i : i + 1], mask=mask[i : i + 1], latent=latent, latent_mask=latent_mask)
        for i in range(len(texts))
    ]


def optimise(
    ttl_start: torch.Tensor,
    start_loss: float,
    prompts: Sequence[Prompt],
    tts: FrozenTTS,
    loss_fn: WaveLoss,
    cfg: AccurateConfig,
    *,
    on_progress: ProgressCallback,
    should_stop: StopCheck,
) -> TimbreResult:
    """Adam on ``style_ttl`` from ``ttl_start`` (``start_loss`` if no step is taken)."""
    ttl = ttl_start.detach().clone().requires_grad_(True)
    optimizer = torch.optim.Adam([ttl], lr=cfg.lr)
    schedule = torch.optim.lr_scheduler.ReduceLROnPlateau(
        optimizer, patience=cfg.lr_patience, factor=cfg.lr_factor, min_lr=cfg.min_lr
    )
    best_ttl, best_loss, best_step = ttl_start.detach().clone(), start_loss, 0
    taken, stopped = 0, False

    while taken < cfg.num_steps:
        if should_stop():
            stopped = True
            break
        # the scan used sentence 0; upstream's iterator then continues from sentence 1
        prompt = prompts[(taken + 1) % len(prompts)]
        optimizer.zero_grad()
        wav = tts.forward(prompt.ids, prompt.mask, ttl, prompt.latent, prompt.latent_mask)
        loss = loss_fn(wav)
        loss.backward()  # type: ignore[no-untyped-call]
        value = loss.item()
        taken += 1
        if taken == 1 or value < best_loss:  # upstream's best starts at infinity
            best_ttl, best_loss, best_step = ttl.detach().clone(), value, taken
        torch.nn.utils.clip_grad_norm_([ttl], cfg.grad_clip)
        optimizer.step()
        schedule.step(value)
        if taken % cfg.log_every == 0:
            lr = optimizer.param_groups[0]["lr"]
            on_progress(
                progress(
                    "timbre",
                    f"step {taken}: loss {value:.4f} (best {best_loss:.4f}, lr {lr:.2e})",
                    step=taken,
                    total=cfg.num_steps,
                    loss=best_loss,
                )
            )
        if best_loss <= cfg.threshold:
            break
    if taken % cfg.log_every != 0:
        on_progress(
            progress(
                "timbre",
                f"timbre done after {taken} steps: best loss {best_loss:.4f}",
                step=taken,
                total=cfg.num_steps,
                loss=best_loss,
            )
        )
    return TimbreResult(best_ttl, best_loss, best_step, taken, stopped)
