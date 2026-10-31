"""Voice pitch for the build methods: a median F0 estimator and the pitch-gated start choice.

Both build losses (ECAPA cosine for ``accurate``, WavLM statistics for ``fast``) barely see
pitch, and the timbre descent does not leave the start preset's pitch region. So the preset
scan only lets presets near the recording's pitch compete (:func:`choose_start`), and the
report says whether the built voice ended up near it (:func:`pitch_report`).

Plain numpy (no torch, no librosa), so it runs and is tested anywhere.

The estimator is YIN (de Cheveigné and Kawahara, 2002, steps 1 to 5): in 40 ms frames every
10 ms, the cumulative mean normalised difference function (CMNDF) of the frame is searched
for its first dip below :data:`THRESHOLD` with a period inside 60 to 400 Hz; the dip's local
minimum, refined by parabolic interpolation, gives the frame's F0. Frames without such a dip
(noise, breath) or much quieter than the loud part of the recording (silence) are unvoiced.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any

import numpy as np

F0_MIN = 60.0
"""Lowest F0 searched (Hz)."""
F0_MAX = 400.0
"""Highest F0 searched (Hz)."""
FRAME_S = 0.040
"""Analysis frame: the difference window plus the longest period searched."""
HOP_S = 0.010
THRESHOLD = 0.2
"""CMNDF dip that marks a frame as voiced (YIN suggests 0.1 to 0.2)."""
QUIET = 0.05
"""Frames below this fraction of the 95th-percentile frame RMS are silence."""
MIN_VOICED = 10
"""Fewer voiced frames than this (0.1 s) and the pitch is unknown."""
PITCH_TOLERANCE = 0.2
"""Largest ``|ln(f0 / reference)|`` that still counts as the same pitch (about ±22%)."""
FALLBACK_COUNT = 2
"""Presets nearest by pitch that compete when none is within the tolerance."""
_CHUNK = 256  # frames per FFT batch, to bound memory on long recordings


def _frames(x: np.ndarray, length: int, hop: int) -> np.ndarray:
    count = 1 + (len(x) - length) // hop
    starts = np.arange(count)[:, None] * hop
    out: np.ndarray = x[starts + np.arange(length)[None, :]]
    return out


def _cmndf(frames: np.ndarray, window: int, max_lag: int) -> np.ndarray:
    """YIN steps 2 and 3 for each row of ``frames``. -> [frames, max_lag + 1]."""
    length = frames.shape[1]
    n = 1 << (length - 1).bit_length()
    head = np.zeros_like(frames)
    head[:, :window] = frames[:, :window]
    # r(tau) = sum_{j < window} x_j x_{j+tau}; no wrap-around because head is zero past window
    r = np.fft.irfft(np.conj(np.fft.rfft(head, n)) * np.fft.rfft(frames, n), n)[:, : max_lag + 1]
    sq = np.concatenate([np.zeros((len(frames), 1)), np.cumsum(frames**2, axis=1)], axis=1)
    lags = np.arange(max_lag + 1)
    energy_tau = sq[:, lags + window] - sq[:, lags]
    diff = np.maximum(sq[:, window : window + 1] + energy_tau - 2 * r, 0.0)
    running = np.cumsum(diff[:, 1:], axis=1)
    out = np.ones_like(diff)
    with np.errstate(divide="ignore", invalid="ignore"):
        norm = diff[:, 1:] * lags[1:] / running
    out[:, 1:] = np.where(running > 0, norm, 1.0)
    return out


def _frame_f0(d: np.ndarray, sr: int, min_lag: int, max_lag: int) -> float | None:
    """YIN steps 4 and 5 on one frame's CMNDF."""
    below = np.flatnonzero(d[min_lag : max_lag + 1] < THRESHOLD)
    if below.size == 0:
        return None
    tau = min_lag + int(below[0])
    while tau + 1 <= max_lag and d[tau + 1] < d[tau]:
        tau += 1
    shift = 0.0
    if min_lag < tau < max_lag:
        a, b, c = d[tau - 1], d[tau], d[tau + 1]
        curve = a - 2 * b + c
        if curve > 0:
            shift = 0.5 * (a - c) / curve
    f0 = sr / (tau + shift)
    return f0 if F0_MIN <= f0 <= F0_MAX else None


def median_f0(wav: np.ndarray, sr: int) -> float | None:
    """Median F0 in Hz of the voiced frames of ``wav`` (1-D, any amplitude), or ``None``.

    ``None`` when fewer than :data:`MIN_VOICED` frames are voiced (silence, noise, too short).
    """
    x = np.asarray(wav, dtype=np.float64).reshape(-1)
    length, hop = round(FRAME_S * sr), max(1, round(HOP_S * sr))
    min_lag, max_lag = int(sr / F0_MAX), math.ceil(sr / F0_MIN)
    window = length - max_lag
    if window <= 0 or len(x) < length or not np.isfinite(x).all():
        return None
    frames = _frames(x, length, hop)
    rms = np.sqrt(np.mean(frames[:, :window] ** 2, axis=1))
    loud = float(np.percentile(rms, 95))
    keep = frames[(rms > QUIET * loud) & (rms > 1e-5)]
    f0s: list[float] = []
    for start in range(0, len(keep), _CHUNK):
        for d in _cmndf(keep[start : start + _CHUNK], window, max_lag):
            f0 = _frame_f0(d, sr, min_lag, max_lag)
            if f0 is not None:
                f0s.append(f0)
    return float(np.median(f0s)) if len(f0s) >= MIN_VOICED else None


def log_distance(a: float, b: float) -> float:
    """``|ln(a / b)|``: 0 for the same pitch, about 0.69 for an octave apart."""
    return abs(math.log(a / b))


def _lowest(indices: Sequence[int], losses: Sequence[float]) -> int:
    return min(indices, key=lambda i: losses[i])


def choose_start(
    scored: Sequence[tuple[float, float | None]], reference_f0: float | None
) -> tuple[int, str]:
    """Pick the start preset from ``(loss, f0)`` per preset; ``(index, reason)``.

    The presets within :data:`PITCH_TOLERANCE` of ``reference_f0`` compete; when none is,
    the :data:`FALLBACK_COUNT` nearest by pitch do. Among them the lowest loss wins. Without
    a reference pitch (or any preset pitch) the lowest loss over all presets wins.
    """
    if not scored:
        raise ValueError("no presets were measured")
    losses = [loss for loss, _ in scored]
    everyone = range(len(scored))
    if reference_f0 is None:
        return _lowest(everyone, losses), "the recording's pitch is unclear; lowest loss"
    pitched = {
        i: log_distance(f0, reference_f0) for i, (_, f0) in enumerate(scored) if f0 is not None
    }
    if not pitched:
        return _lowest(everyone, losses), "no preset's pitch is clear; lowest loss"
    near = [i for i, dist in pitched.items() if dist <= PITCH_TOLERANCE]
    ref = f"{reference_f0:.0f} Hz"
    if near:
        return _lowest(near, losses), f"lowest loss of {len(near)} presets near {ref}"
    nearest = sorted(pitched, key=pitched.__getitem__)[:FALLBACK_COUNT]
    return _lowest(nearest, losses), f"no preset near {ref}; lowest loss of the nearest by pitch"


def pitch_report(reference_f0: float | None, voice_f0: float | None) -> dict[str, Any]:
    """The report's pitch keys; ``pitch_match`` is ``None`` when either pitch is unknown."""
    match = (
        None
        if reference_f0 is None or voice_f0 is None
        else log_distance(voice_f0, reference_f0) <= PITCH_TOLERANCE
    )
    return {
        "pitch_reference_hz": None if reference_f0 is None else round(reference_f0, 1),
        "pitch_voice_hz": None if voice_f0 is None else round(voice_f0, 1),
        "pitch_match": match,
    }


def describe_hz(f0: float | None) -> str:
    """``"198 Hz"``, or ``"no clear pitch"``, for progress messages."""
    return "no clear pitch" if f0 is None else f"{f0:.0f} Hz"
