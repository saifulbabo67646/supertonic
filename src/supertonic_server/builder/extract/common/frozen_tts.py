# Adapted from supertonic.embed (src/frozen_tts.py)
# https://github.com/kdrkdrkdr/supertonic.embed @ 6c38a94af2c429d7f4098708686af80d23ccadc0
# Copyright (c) 2026 Gyeongmin Kim. MIT License (see LICENSE-supertonic-embed).
# The onnx2torch shape-inference patch follows supertonic3-voice-clone (utils/model.py)
# https://github.com/saurabhv749/supertonic3-voice-clone @ 765ce5e27daa8d30937e2d0d8f9730280add5748
# Copyright (c) Saurabh Verma. MIT License.
# Adapted: paths, device, speed, flow steps and seed are arguments instead of module
# globals; the tokenizer is the `supertonic` package's own UnicodeProcessor (the Supertonic 3
# text front end, all languages) instead of a vendored copy; prompt latents are sized from a
# caller-chosen preset; typed; no TLS-verification bypass or environment changes.
"""The released Supertonic 3 as frozen, differentiable PyTorch.

The four ONNX modules are converted so gradients can reach a style vector; every converted
parameter is frozen. A :class:`Prompt` is a sentence with the fixed noise latent it is
always synthesised from, so the only thing that changes during a descent is the style.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import onnx
import onnx2torch
import onnxslim
import torch
from onnx import shape_inference
from onnx2torch import convert
from supertonic.core import UnicodeProcessor

logger = logging.getLogger(__name__)

SR = 44100  # Supertonic output rate
TARGET_OPSET = 17  # newest opset onnx2torch converts these graphs at
MODULES = ("duration_predictor", "text_encoder", "vector_estimator", "vocoder")


def _infer_shapes_in_memory(model: Any) -> Any:
    """onnx2torch's ``safe_shape_inference`` writes temp files; infer in memory instead."""
    if isinstance(model, str | Path):
        model = onnx.load(str(model))
    try:
        return shape_inference.infer_shapes(model)
    except Exception:  # shape inference is an optimisation; convert without it
        return model


onnx2torch.converter.safe_shape_inference = _infer_shapes_in_memory


def _load_frozen(onnx_dir: Path, name: str, device: torch.device) -> torch.nn.Module:
    """Slim one released ONNX module, drop it to opset 17, convert, freeze."""
    slimmed = onnxslim.slim(str(onnx_dir / f"{name}.onnx"))
    for opset in slimmed.opset_import:
        if opset.domain in ("", "ai.onnx"):
            opset.version = TARGET_OPSET
    for node in slimmed.graph.node:
        if node.op_type == "Clip":  # onnx2torch rejects trailing empty inputs
            kept = list(node.input)
            while kept and kept[-1] == "":
                kept.pop()
            del node.input[:]
            node.input.extend(kept)
    module: torch.nn.Module = convert(slimmed).eval()
    for p in module.parameters():
        p.requires_grad_(False)
    return module.to(device)


@dataclass
class Prompt:
    """A sentence and the fixed noise latent it is synthesised from."""

    ids: torch.Tensor  # [1, T]
    mask: torch.Tensor  # [1, 1, T]
    latent: torch.Tensor  # [1, D, L]
    latent_mask: torch.Tensor  # [1, 1, L]


class FrozenTTS:
    """The four modules, the tokenizer, and the latent geometry tying them together."""

    def __init__(
        self, onnx_dir: Path, device: torch.device, *, total_step: int, speed: float, seed: int
    ) -> None:
        self.device = device
        self.total_step = total_step
        self.speed = speed
        self.seed = seed
        self.text = UnicodeProcessor(str(onnx_dir / "unicode_indexer.json"))
        self.duration = _load_frozen(onnx_dir, "duration_predictor", device)
        self.text_encoder = _load_frozen(onnx_dir, "text_encoder", device)
        self.vector_estimator = _load_frozen(onnx_dir, "vector_estimator", device)
        self.vocoder = _load_frozen(onnx_dir, "vocoder", device)
        cfg = json.loads((onnx_dir / "tts.json").read_text(encoding="utf-8"))
        compress = int(cfg["ttl"]["chunk_compress_factor"])
        self.chunk = int(cfg["ae"]["base_chunk_size"]) * compress  # samples per latent frame
        self.latent_dim = int(cfg["ttl"]["latent_dim"]) * compress

    def encode(self, text: str, lang: str = "en") -> tuple[torch.Tensor, torch.Tensor]:
        """-> ``(ids [1,T], mask [1,1,T])`` on the device."""
        ids, mask = self.text([text], lang)
        return (
            torch.tensor(ids, dtype=torch.int64, device=self.device),
            torch.tensor(mask, dtype=torch.float32, device=self.device),
        )

    def seconds(self, ids: torch.Tensor, mask: torch.Tensor, style_dp: torch.Tensor) -> Any:
        """Predicted duration in seconds (differentiable), shaped ``[B]``."""
        return self.duration(ids, style_dp, mask) / self.speed

    def forward(
        self,
        ids: torch.Tensor,
        mask: torch.Tensor,
        style_ttl: torch.Tensor,
        latent: torch.Tensor,
        latent_mask: torch.Tensor,
    ) -> torch.Tensor:
        """Text encoder, flow-matching steps and vocoder, differentiably. -> waveform."""
        b = style_ttl.shape[0]
        text_emb = self.text_encoder(ids, style_ttl, mask)
        x = latent * latent_mask
        total = torch.full((b,), float(self.total_step), device=self.device)
        for step in range(self.total_step):
            now = torch.full((b,), float(step), device=self.device)
            x = self.vector_estimator(x, text_emb, style_ttl, latent_mask, mask, now, total)
        wav: torch.Tensor = self.vocoder(x)
        return wav

    def predict_seconds(self, prompt: Prompt, style_dp: torch.Tensor) -> float:
        """How long this duration style says the prompt takes."""
        with torch.no_grad():
            return float(self.seconds(prompt.ids, prompt.mask, style_dp).reshape(()))

    def synthesize(self, prompt: Prompt, style_ttl: torch.Tensor) -> torch.Tensor:
        """The prompt at its fixed latent length. -> 1-D waveform."""
        with torch.no_grad():
            wav = self.forward(
                prompt.ids, prompt.mask, style_ttl, prompt.latent, prompt.latent_mask
            )
        return wav.reshape(-1)

    def synthesize_at_own_length(
        self, prompt: Prompt, style_ttl: torch.Tensor, style_dp: torch.Tensor
    ) -> np.ndarray:
        """The prompt at the length *this* duration style commands, as inference does."""
        seconds = self.predict_seconds(prompt, style_dp)
        frames = max(4, int(np.ceil(int(seconds * SR) / self.chunk)))
        generator = torch.Generator(device="cpu").manual_seed(self.seed)
        latent = torch.randn(1, self.latent_dim, frames, generator=generator).to(self.device)
        latent_mask = torch.ones(1, 1, frames, device=self.device)
        with torch.no_grad():
            wav = self.forward(prompt.ids, prompt.mask, style_ttl, latent, latent_mask)
        out: np.ndarray = wav.reshape(-1).cpu().numpy()
        return out

    def build_prompts(
        self, texts: Sequence[str], sizing_dp: torch.Tensor, lang: str = "en"
    ) -> list[Prompt]:
        """One prompt per sentence, each with its own fixed latent.

        The latent length comes from one preset's predicted duration (``sizing_dp``), the
        same for every speaker, so two descents differ only in timbre, never in length.
        """
        torch.manual_seed(self.seed)
        rng = np.random.RandomState(self.seed)
        prompts = []
        for text in texts:
            ids, mask = self.encode(text, lang)
            with torch.no_grad():
                seconds = float(self.seconds(ids, mask, sizing_dp).reshape(()))
            frames = int(np.ceil(int(seconds * SR) / self.chunk))
            latent = rng.randn(1, self.latent_dim, frames).astype(np.float32)
            prompts.append(
                Prompt(
                    ids=ids,
                    mask=mask,
                    latent=torch.tensor(latent, device=self.device),
                    latent_mask=torch.ones(1, 1, frames, device=self.device),
                )
            )
        return prompts


def load_frozen_tts(
    onnx_dir: Path,
    device: str | torch.device,
    *,
    total_step: int = 5,
    speed: float = 1.05,
    seed: int = 42,
) -> FrozenTTS:
    """Convert the Supertonic 3 ONNX modules in ``onnx_dir`` to frozen torch on ``device``.

    Args:
        onnx_dir: ``<model_dir>/onnx``.
        device: Torch device.
        total_step: Flow-matching steps per synthesis.
        speed: Speed factor dividing the predicted duration.
        seed: Fixes the noise latents, so runs repeat.
    """
    for name in MODULES:
        if not (onnx_dir / f"{name}.onnx").exists():
            raise FileNotFoundError(f"missing Supertonic ONNX module: {onnx_dir / name}.onnx")
    logger.info("converting Supertonic ONNX modules from %s", onnx_dir)
    return FrozenTTS(onnx_dir, torch.device(device), total_step=total_step, speed=speed, seed=seed)
