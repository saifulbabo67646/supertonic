"""Reading reference recordings for the extractors (soundfile + librosa; never torchaudio)."""

from __future__ import annotations

from pathlib import Path

import librosa
import numpy as np
import soundfile as sf


def load_mono(path: Path, sr: int) -> np.ndarray:
    """Decode ``path`` with soundfile, mix to mono and resample to ``sr``. -> float32 [N]."""
    data, file_sr = sf.read(str(path), dtype="float32", always_2d=True)
    mono = data.mean(axis=1)
    if file_sr != sr:
        mono = librosa.resample(mono, orig_sr=file_sr, target_sr=sr)
    out: np.ndarray = np.ascontiguousarray(mono, dtype=np.float32)
    return out
