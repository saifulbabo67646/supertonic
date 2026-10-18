"""Estimated word / character timing from rendered audio (no forced alignment)."""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass

import numpy as np

FRAME_MS = 10
SILENCE_DB = 40.0
_SOFT_PAUSE = frozenset(",;:、，；：")
_HARD_PAUSE = frozenset(".!?。！？．…‥")
_SOFT_WEIGHT = 2
_HARD_WEIGHT = 3


@dataclass(frozen=True)
class Span:
    """A piece of text with its estimated time range in milliseconds."""

    text: str
    start_ms: int
    end_ms: int


def speech_bounds(audio: np.ndarray, sr: int) -> tuple[int, int]:
    """Return the first and last sample (exclusive) of audible speech.

    Audible means a 10 ms frame whose RMS is within 40 dB of the loudest frame. Silent or
    empty clips return the whole clip ``(0, len(audio))``.
    """
    n = len(audio)
    frame = max(1, sr * FRAME_MS // 1000)
    frames = n // frame
    if frames == 0:
        return 0, n
    x = audio[: frames * frame].astype(np.float64).reshape(frames, frame)
    rms = np.sqrt(np.mean(x * x, axis=1))
    peak = float(rms.max())
    if peak <= 0.0:
        return 0, n
    loud = np.flatnonzero(rms >= peak * 10 ** (-SILENCE_DB / 20))
    start = int(loud[0]) * frame
    end = n if int(loud[-1]) == frames - 1 else (int(loud[-1]) + 1) * frame
    return start, end


def _pause(ch: str) -> int:
    if ch in _HARD_PAUSE:
        return _HARD_WEIGHT
    if ch in _SOFT_PAUSE:
        return _SOFT_WEIGHT
    return 0


def _is_punct(ch: str) -> bool:
    return unicodedata.category(ch).startswith("P")


def _spaced_tokens(text: str) -> list[tuple[str, float]]:
    out: list[tuple[str, float]] = []
    for word in text.split():
        body = sum(1 for c in word if c.isalnum())
        out.append((word, float(max(1, body) + _pause(word[-1]))))
    return out


def _char_tokens(text: str) -> list[tuple[str, float]]:
    out: list[tuple[str, float]] = []
    for ch in text:
        if ch.isspace():
            continue
        if _is_punct(ch):
            if out:
                out[-1] = (out[-1][0], out[-1][1] + _pause(ch))
            continue
        out.append((ch, 1.0))
    return out


def estimate_spans(
    text: str, audio: np.ndarray, sr: int, spaced: bool, offset_ms: int = 0
) -> list[Span]:
    """Split ``text`` into words (``spaced``) or characters and time them across the speech.

    The speech bounds of ``audio`` are divided proportionally to each token's weight: letters
    and digits for words, one per character, plus a pause allowance for trailing punctuation.
    Spans are contiguous, monotonic and at least 1 ms long. Pure numpy and deterministic.

    Args:
        text: The text that ``audio`` speaks.
        audio: Mono float samples.
        sr: Sample rate of ``audio``.
        spaced: Whether the language separates words with spaces.
        offset_ms: Added to every time (start of this clip in a longer recording).
    """
    tokens = _spaced_tokens(text) if spaced else _char_tokens(text)
    if not tokens:
        return []
    first, last = speech_bounds(audio, sr)
    start_ms = first * 1000 / sr
    span_ms = max(0.0, (last - first) * 1000 / sr)
    total = sum(w for _, w in tokens)
    edges: list[int] = []
    acc = 0.0
    prev = round(start_ms)
    for _, weight in tokens:
        acc += weight
        edge = max(round(start_ms + span_ms * acc / total), prev + 1)
        edges.append(edge)
        prev = edge
    begins = [round(start_ms), *edges[:-1]]
    return [
        Span(tok, offset_ms + b, offset_ms + e)
        for (tok, _), b, e in zip(tokens, begins, edges, strict=True)
    ]
