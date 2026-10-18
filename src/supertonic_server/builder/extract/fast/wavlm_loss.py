# Adapted from supertonic.embed (src/wavlm_loss.py)
# https://github.com/kdrkdrkdr/supertonic.embed @ 6c38a94af2c429d7f4098708686af80d23ccadc0
# Copyright (c) 2026 Gyeongmin Kim. MIT License (see LICENSE-supertonic-embed).
# Adapted: upstream's TLS-verification bypass (httpx monkeypatch) and its removal of
# certificate environment variables are deliberately NOT included; device and layer are
# arguments; the reference is decoded with soundfile; transformers is imported lazily;
# typed.
"""The objective the timbre is inverted against: WavLM layer statistics.

A voice is the mean and standard deviation over time of one WavLM-Large layer. Pooling
over time makes the loss independent of what is said, and it is the same pooling x-vector
speaker embeddings use. Layer 4 is where Chiu et al. (2025) found speaker identity peaks;
HuggingFace's ``hidden_states[4]`` is that layer.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import torch
import torch.nn.functional as F

from supertonic_server.builder.extract.common.audio import load_mono
from supertonic_server.builder.extract.common.frozen_tts import SR
from supertonic_server.builder.extract.fast.config import WAVLM_REPO, WAVLM_SR

Stats = tuple[torch.Tensor, torch.Tensor]


def load_wavlm(device: torch.device) -> Any:
    """WavLM-Large, frozen (downloaded to the Hugging Face cache on first use)."""
    from transformers import WavLMModel  # imported here so the loss maths needs only torch

    model = WavLMModel.from_pretrained(WAVLM_REPO).to(device).eval()  # type: ignore[arg-type]
    for p in model.parameters():
        p.requires_grad_(False)
    return model


def to_wavlm_rate(wav: torch.Tensor) -> torch.Tensor:
    """44.1 kHz to 16 kHz, differentiably, keeping the batch dimension."""
    if wav.ndim == 1:
        wav = wav.unsqueeze(0)
    n = int(round(wav.shape[-1] * WAVLM_SR / SR))
    out = F.interpolate(wav.unsqueeze(1), size=n, mode="linear", align_corners=False)
    return out.squeeze(1)


def layer_stats(wavlm: Any, wav16: torch.Tensor, layer: int) -> Stats:
    """``(mean, std)`` over time of the chosen layer, each ``[B, D]``."""
    h = wavlm(wav16, output_hidden_states=True).hidden_states[layer]
    return h.mean(dim=1), h.std(dim=1)


def style_loss(synthesized: Stats, target: Stats) -> torch.Tensor:
    """Mean squared error between two ``(mean, std)`` pairs."""
    return F.mse_loss(synthesized[0], target[0]) + F.mse_loss(synthesized[1], target[1])


def target_from_file(wavlm: Any, path: Path, layer: int, device: torch.device) -> Stats:
    """The statistics of a reference recording, at any input sample rate."""
    y = load_mono(path, WAVLM_SR)
    wav = torch.tensor(y, dtype=torch.float32, device=device).unsqueeze(0)
    with torch.no_grad():
        return layer_stats(wavlm, wav, layer)
