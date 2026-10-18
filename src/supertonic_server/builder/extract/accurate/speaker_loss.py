# Adapted from supertonic3-voice-clone (utils/loss.py)
# https://github.com/saurabhv749/supertonic3-voice-clone @ 765ce5e27daa8d30937e2d0d8f9730280add5748
# Copyright (c) 2026 Saurabh Verma. MIT License (see LICENSE-supertonic3-voice-clone).
# Adapted: the encoder and the reference are arguments (loading is split out); ECAPA is
# saved under the Hugging Face hub cache and fetched with LocalStrategy.COPY (no symlinks,
# which Windows refuses without developer mode); the reference is decoded with soundfile
# (never torchaudio.load); the 44.1 -> 16 kHz resampler is built once and stays on the
# device instead of moving every generated waveform to the CPU; device is an argument;
# typed. Upstream's TLS-verification bypass and environment changes (utils/model.py) are
# deliberately NOT included. The loss itself, 1 - cosine of ECAPA embeddings, is unchanged.
"""The ``accurate`` objective: speaker similarity under SpeechBrain's ECAPA-TDNN.

ECAPA (``speechbrain/spkrec-ecapa-voxceleb``, Apache-2.0) embeds a 16 kHz recording as a
192-dimensional speaker vector. The loss of a synthesis is one minus the cosine between its
embedding and the reference's, so 0 means the same speaker as far as ECAPA can tell.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import soundfile as sf
import torch
import torch.nn.functional as F
import torchaudio

from supertonic_server.builder.extract.accurate.config import (
    ECAPA_SAVEDIR_NAME,
    ECAPA_SOURCE,
    ECAPA_SR,
)
from supertonic_server.builder.extract.common.frozen_tts import SR

logger = logging.getLogger(__name__)


def ecapa_savedir() -> Path:
    """Where ECAPA is kept: ``<Hugging Face hub cache>/supertonic-ecapa``.

    The hub cache honours ``HF_HUB_CACHE`` / ``HF_HOME`` (default
    ``~/.cache/huggingface/hub``), so ECAPA sits beside WavLM and Supertonic.
    """
    from huggingface_hub import constants

    return Path(constants.HF_HUB_CACHE) / ECAPA_SAVEDIR_NAME


def load_ecapa(device: torch.device) -> Any:
    """ECAPA-TDNN on ``device``, frozen (downloaded on first use, ~80 MB)."""
    from speechbrain.inference.speaker import EncoderClassifier
    from speechbrain.utils.fetching import LocalStrategy

    savedir = ecapa_savedir()
    logger.info("loading %s into %s", ECAPA_SOURCE, savedir)
    encoder = EncoderClassifier.from_hparams(
        source=ECAPA_SOURCE,
        savedir=str(savedir),
        run_opts={"device": str(device)},
        local_strategy=LocalStrategy.COPY,
    )
    if encoder is None:  # only with download_only=True
        raise RuntimeError(f"could not load {ECAPA_SOURCE}")
    encoder.eval()
    for p in encoder.parameters():
        p.requires_grad_(False)
    return encoder


def load_reference16(path: Path, device: torch.device) -> torch.Tensor:
    """The reference recording as 16 kHz mono on ``device``. -> ``[1, T]``."""
    data, file_sr = sf.read(str(path), dtype="float32", always_2d=True)
    wav = torch.tensor(data.mean(axis=1), dtype=torch.float32, device=device).unsqueeze(0)
    if file_sr != ECAPA_SR:
        resample = torchaudio.transforms.Resample(orig_freq=file_sr, new_freq=ECAPA_SR)
        wav = resample.to(device)(wav)
    return wav


class SpeakerLoss:
    """``1 - cosine(ECAPA(reference), ECAPA(generated))``, differentiable in the generated audio.

    The reference is embedded once, here.
    """

    def __init__(self, encoder: Any, reference16: torch.Tensor, device: torch.device) -> None:
        self.encoder = encoder
        self.resample = torchaudio.transforms.Resample(orig_freq=SR, new_freq=ECAPA_SR).to(device)
        with torch.no_grad():
            self.reference = F.normalize(self.embed(reference16), p=2, dim=0)

    def embed(self, wav16: torch.Tensor) -> torch.Tensor:
        """ECAPA embedding of a 16 kHz ``[1, T]`` waveform. -> ``[D]``."""
        embedding: torch.Tensor = self.encoder.encode_batch(wav16)
        return embedding.reshape(-1)

    def __call__(self, wav44: torch.Tensor) -> torch.Tensor:
        """The loss of one 44.1 kHz synthesis (any shape holding one waveform). -> scalar."""
        generated = F.normalize(self.embed(self.resample(wav44.reshape(1, -1))), p=2, dim=0)
        return 1 - torch.dot(self.reference, generated)
