# Adapted from supertonic.embed (src/invert_ttl.py, nearest-preset initialisation)
# https://github.com/kdrkdrkdr/supertonic.embed @ 6c38a94af2c429d7f4098708686af80d23ccadc0
# Copyright (c) 2026 Gyeongmin Kim. MIT License (see LICENSE-supertonic-embed).
# The same scan is in supertonic3-voice-clone (train_style.py, `--reference-style auto`)
# https://github.com/saurabhv749/supertonic3-voice-clone @ 765ce5e27daa8d30937e2d0d8f9730280add5748
# Copyright (c) 2026 Saurabh Verma. MIT License (see LICENSE-supertonic3-voice-clone).
# Adapted: one scan for both methods, the objective passed in as a loss on the waveform;
# reports each preset through a callback and can be stopped; typed.
"""Pick the shipped preset closest to the reference under a method's objective."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path

import torch

from supertonic_server.builder.extract.base import ProgressCallback, StopCheck, progress
from supertonic_server.builder.extract.common.frozen_tts import FrozenTTS, Prompt
from supertonic_server.builder.extract.common.style_file import load_style

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
) -> tuple[Path, float, bool] | None:
    """``(preset, loss, stopped)`` of the preset whose ``style_ttl`` scores lowest on ``prompt``.

    One ``preset`` progress event per preset measured. ``None`` when stopped before any
    preset was measured; otherwise a stop returns the nearest so far with ``stopped=True``.
    """
    best: tuple[Path, float] | None = None
    for i, path in enumerate(presets, 1):
        if should_stop():
            return None if best is None else (*best, True)
        ttl, _ = load_style(path, tts.device)
        wav = tts.synthesize(prompt, ttl)
        with torch.no_grad():
            loss = float(loss_fn(wav))
        if best is None or loss < best[1]:
            best = (path, loss)
        on_progress(
            progress("preset", f"{path.stem}: {loss:.4f}", step=i, total=len(presets), loss=loss)
        )
    return None if best is None else (*best, False)
