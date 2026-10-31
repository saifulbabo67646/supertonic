# Adapted from supertonic.embed (src/invert_ttl.py, nearest-preset initialisation)
# https://github.com/kdrkdrkdr/supertonic.embed @ 6c38a94af2c429d7f4098708686af80d23ccadc0
# Copyright (c) 2026 Gyeongmin Kim. MIT License (see LICENSE-supertonic-embed).
# The same scan is in supertonic3-voice-clone (train_style.py, `--reference-style auto`)
# https://github.com/saurabhv749/supertonic3-voice-clone @ 765ce5e27daa8d30937e2d0d8f9730280add5748
# Copyright (c) 2026 Saurabh Verma. MIT License (see LICENSE-supertonic3-voice-clone).
# Adapted: one scan for both methods, the objective passed in as a loss on the waveform;
# reports each preset through a callback and can be stopped; only presets near the
# reference's pitch compete (both objectives barely see pitch); typed.
"""Pick the start preset: near the reference's pitch, then closest under the method's loss."""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from pathlib import Path

import torch

from supertonic_server.builder.extract.base import ProgressCallback, StopCheck, progress
from supertonic_server.builder.extract.common.frozen_tts import SR, FrozenTTS, Prompt
from supertonic_server.builder.extract.common.pitch import choose_start, describe_hz, median_f0
from supertonic_server.builder.extract.common.style_file import load_style

logger = logging.getLogger(__name__)

# A method's objective on one synthesised waveform (lower is closer). -> scalar tensor
WaveLoss = Callable[[torch.Tensor], torch.Tensor]


def nearest_preset(
    presets: Sequence[Path],
    prompt: Prompt,
    tts: FrozenTTS,
    loss_fn: WaveLoss,
    *,
    on_progress: ProgressCallback,
    should_stop: StopCheck,
    reference_f0: float | None = None,
) -> tuple[Path, float, bool] | None:
    """``(preset, loss, stopped)`` of the start preset for ``prompt``.

    Each preset's ``style_ttl`` is synthesised once; its loss and the median F0 of that
    waveform are measured. The presets within about ±22% of ``reference_f0`` compete (the
    two nearest by pitch when none is); among them the lowest loss wins (see
    :func:`~supertonic_server.builder.extract.common.pitch.choose_start`). Without
    ``reference_f0`` the lowest loss over all presets wins.

    One ``preset`` progress event per preset measured (``"F4: 0.3123 · 198 Hz"``). ``None``
    when stopped before any preset was measured; otherwise a stop chooses among the presets
    measured so far, with ``stopped=True``.
    """
    measured: list[tuple[Path, float, float | None]] = []
    stopped = False
    for i, path in enumerate(presets, 1):
        if should_stop():
            stopped = True
            break
        ttl, _ = load_style(path, tts.device)
        wav = tts.synthesize(prompt, ttl)
        with torch.no_grad():
            loss = float(loss_fn(wav))
        f0 = median_f0(wav.detach().float().cpu().numpy(), SR)
        measured.append((path, loss, f0))
        message = f"{path.stem}: {loss:.4f} · {describe_hz(f0)}"
        on_progress(progress("preset", message, step=i, total=len(presets), loss=loss))
    if not measured:
        return None
    index, reason = choose_start([(loss, f0) for _, loss, f0 in measured], reference_f0)
    path, loss, f0 = measured[index]
    logger.info("start preset %s (loss %.4f, %s): %s", path.stem, loss, describe_hz(f0), reason)
    return path, loss, stopped
