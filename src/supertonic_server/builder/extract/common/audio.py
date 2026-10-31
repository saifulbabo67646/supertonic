"""Reading reference recordings for the extractors (soundfile + librosa; never torchaudio)."""

from __future__ import annotations

from pathlib import Path

import librosa
import numpy as np
import soundfile as sf

from supertonic_server.builder.extract.common.pitch import median_f0


def check_readable(path: Path) -> None:
    """Fail fast, before any model loads, when ``path`` is missing or not decodable audio."""
    if not Path(path).is_file():
        raise FileNotFoundError(f"reference recording not found: {path}")
    try:
        info = sf.info(str(path))
    except Exception as exc:  # soundfile raises its own error types per backend
        raise ValueError(f"reference recording is not readable audio: {path} ({exc})") from exc
    if info.frames <= 0:
        raise ValueError(f"reference recording is empty: {path}")


def load_mono(path: Path, sr: int) -> np.ndarray:
    """Decode ``path`` with soundfile, mix to mono and resample to ``sr``. -> float32 [N]."""
    data, file_sr = sf.read(str(path), dtype="float32", always_2d=True)
    mono = data.mean(axis=1)
    if file_sr != sr:
        mono = librosa.resample(mono, orig_sr=file_sr, target_sr=sr)
    out: np.ndarray = np.ascontiguousarray(mono, dtype=np.float32)
    return out


PITCH_SR = 16000
"""Rate the reference pitch is measured at (plenty for 60 to 400 Hz)."""


def reference_f0(path: Path) -> float | None:
    """Median F0 of the reference recording in Hz, or ``None`` when it is unclear."""
    return median_f0(load_mono(path, PITCH_SR), PITCH_SR)
