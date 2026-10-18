# Adapted from supertonic.embed (src/invert_dp.py)
# https://github.com/kdrkdrkdr/supertonic.embed @ 6c38a94af2c429d7f4098708686af80d23ccadc0
# Copyright (c) 2026 Gyeongmin Kim. MIT License (see LICENSE-supertonic-embed).
# Adapted: settings come from a DurationConfig argument instead of config.yaml; progress
# is reported through a callback after every iteration; a stop check is polled every
# optimiser step and ends the search with the best duration style so far ("stopped");
# typed. The algorithm and its constants are unchanged.
"""Recover the duration style by matching the reference speaking rate.

A time-pooled loss cannot see tempo, so rate is measured on audio and ``style_dp`` is
inverted through the frozen duration predictor. A fixed-point iteration on a duration
multiplier rho does it: fit dp to the starting durations times rho, synthesise at the
length that dp commands, measure the rate, take a secant step in log space toward the
reference rate. It stops when the rates match, when two moves in a row fail to improve,
or when length stops turning into tempo.

The same detector runs on reference and synthesis, so its bias cancels.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import librosa
import numpy as np
import torch
from scipy.signal import find_peaks

from supertonic_server.builder.extract.base import ProgressCallback, StopCheck, progress
from supertonic_server.builder.extract.common.frozen_tts import SR, FrozenTTS, Prompt

RATE_SR = 16000  # rate detector sample rate


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


def nuclei_rate(
    wav16: np.ndarray, min_distance_s: float = 0.10, prominence: float = 0.08
) -> float | None:
    """Syllable nuclei per second: peaks of the smoothed RMS envelope of the trimmed clip.

    ``None`` if the clip is too short to measure.
    """
    trimmed, _ = librosa.effects.trim(wav16, top_db=35)
    seconds = len(trimmed) / RATE_SR
    if seconds < 0.3:
        return None
    envelope = librosa.feature.rms(y=trimmed, frame_length=400, hop_length=160)[0]
    envelope = np.convolve(envelope, np.ones(5) / 5, mode="same")
    peaks, _ = find_peaks(
        envelope,
        distance=max(1, int(min_distance_s * RATE_SR / 160)),
        prominence=prominence * envelope.max(),
    )
    return len(peaks) / seconds


def synthesized_rate(
    prompts: Sequence[Prompt], ttl: torch.Tensor, dp: torch.Tensor, tts: FrozenTTS
) -> float | None:
    """Mean rate over the prompts, each synthesised at the length dp commands."""
    rates = []
    for prompt in prompts:
        wav = tts.synthesize_at_own_length(prompt, ttl, dp)
        rate = nuclei_rate(librosa.resample(wav, orig_sr=SR, target_sr=RATE_SR))
        if rate is not None:
            rates.append(rate)
    return float(np.mean(rates)) if rates else None


def _fit_to_durations(
    prompts: Sequence[Prompt],
    targets: Sequence[float],
    tts: FrozenTTS,
    dp_start: torch.Tensor,
    cfg: DurationConfig,
    should_stop: StopCheck,
) -> torch.Tensor | None:
    """The unit-row ``style_dp`` whose predicted durations hit the targets.

    A prior toward the starting vector keeps the answer plausible among the many dp values
    that give the same duration. ``None`` when a stop was requested mid-fit.
    """
    dp = dp_start.clone().requires_grad_(True)
    anchor = dp_start.detach().clone()
    optimizer = torch.optim.Adam([dp], lr=cfg.invert_lr)
    wanted = torch.tensor(list(targets), dtype=torch.float32, device=dp_start.device)
    for _ in range(cfg.invert_steps):
        if should_stop():
            return None
        optimizer.zero_grad()
        predicted = torch.stack([tts.seconds(p.ids, p.mask, dp).reshape(()) for p in prompts])
        loss = ((predicted - wanted) ** 2).mean() + cfg.invert_prior * ((dp - anchor) ** 2).sum()
        loss.backward()  # type: ignore[no-untyped-call]
        optimizer.step()
        with torch.no_grad():
            dp /= dp.norm(dim=-1, keepdim=True).clamp_min(1e-8)
    return dp.detach()


def duration_inversion(
    reference16: np.ndarray,
    ttl: torch.Tensor,
    dp_start: torch.Tensor,
    prompts: Sequence[Prompt],
    tts: FrozenTTS,
    cfg: DurationConfig,
    *,
    on_progress: ProgressCallback,
    should_stop: StopCheck,
) -> tuple[torch.Tensor, dict[str, Any]]:
    """Recover ``style_dp`` for one speaker. -> ``(style_dp, report)``.

    ``reference16`` is the reference recording at 16 kHz. The report holds the rates, the
    multiplier reached, why the iteration stopped (``status``) and the path it took.
    """
    reference_rate = nuclei_rate(reference16)
    if reference_rate is None:
        return dp_start, {"status": "reference too short", "rate_ref": None, "rate_final": None}
    if should_stop():
        return dp_start, {
            "status": "stopped",
            "rate_ref": round(reference_rate, 3),
            "rate_final": None,
        }
    start_durations = [tts.predict_seconds(p, dp_start) for p in prompts]
    start_rate = synthesized_rate(prompts, ttl, dp_start, tts)
    if start_rate is None:
        return dp_start, {
            "status": "starting synthesis unmeasurable",
            "rate_ref": round(reference_rate, 3),
            "rate_final": None,
        }

    wanted = math.log(reference_rate)
    log_rho, log_rate = [0.0], [math.log(start_rate)]
    slope = -1.0  # shorter clip, faster speech
    best: dict[str, Any] = {
        "error": abs(start_rate / reference_rate - 1),
        "rho": 1.0,
        "rate": start_rate,
        "dp": dp_start,
        "fit_error": 0.0,
    }
    path = [[1.0, round(start_rate, 3)]]
    status, stalled = "out of iterations", 0

    for iteration in range(1, cfg.max_iters + 1):
        move = (wanted - log_rate[-1]) / slope
        move = max(-cfg.max_log_step, min(cfg.max_log_step, move))
        asked = math.exp(log_rho[-1] + move)
        targets = [d * asked for d in start_durations]

        dp = _fit_to_durations(prompts, targets, tts, dp_start, cfg, should_stop)
        if dp is None:
            status = "stopped"
            break
        commanded = [tts.predict_seconds(p, dp) for p in prompts]
        rho = float(np.mean([a / b for a, b in zip(commanded, start_durations, strict=True)]))
        rate = synthesized_rate(prompts, ttl, dp, tts)
        if rate is None:
            status = "unmeasurable"
            break

        x, y = math.log(rho), math.log(rate)
        path.append([round(rho, 3), round(rate, 3)])
        error = abs(rate / reference_rate - 1)
        if error < best["error"]:
            pairs = zip(commanded, targets, strict=True)
            fit_error = float(np.mean([abs(a / t - 1) for a, t in pairs]))
            best = {"error": error, "rho": rho, "rate": rate, "dp": dp, "fit_error": fit_error}
            stalled = 0
        else:
            stalled += 1
        on_progress(
            progress(
                "duration",
                f"speaking rate {rate:.2f}/s against {reference_rate:.2f}/s",
                step=iteration,
                total=cfg.max_iters,
            )
        )

        if error < cfg.tolerance:
            status = "converged"
            break
        if stalled >= 2:  # below what the detector resolves
            status = "noise floor"
            break
        travelled = x - log_rho[0]
        if (
            abs(travelled) >= cfg.saturation_move
            and (y - log_rate[0]) / travelled > cfg.saturation_slope
        ):
            status = "saturated"  # length moved, tempo did not follow
            break
        recent = x - log_rho[-1]  # update the slope only over a clear move
        if abs(recent) >= cfg.min_response_move:
            measured = (y - log_rate[-1]) / recent
            if measured < -0.05:
                slope = max(-3.0, min(-0.33, measured))
        log_rho.append(x)
        log_rate.append(y)

    best_dp: torch.Tensor = best["dp"]
    row_norms = best_dp.norm(dim=-1).flatten().tolist()
    report = {
        "rate_ref": round(reference_rate, 3),
        "rate_start": round(start_rate, 3),
        "rate_final": round(best["rate"], 3),
        "rho": round(best["rho"], 3),
        "status": status,
        "iters": len(path) - 1,
        "path": path,
        "duration_fit_error": round(best["fit_error"], 4),
        "seconds_start": round(start_durations[0], 2),
        "seconds_final": round(start_durations[0] * best["rho"], 2),
        "row_norm_error": round(max(abs(n - 1) for n in row_norms), 7),
    }
    return best_dp, report
