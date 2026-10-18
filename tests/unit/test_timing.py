"""Tests for speech bounds and estimated word/character spans."""

from __future__ import annotations

import numpy as np

from supertonic_server.audio import estimate_spans, speech_bounds


def tone(ms: int, sr: int = 44100, lead_ms: int = 0, tail_ms: int = 0) -> np.ndarray:
    def z(m: int) -> np.ndarray:
        return np.zeros(int(sr * m / 1000), np.float32)

    return np.concatenate(
        [
            z(lead_ms),
            0.5 * np.sin(np.arange(int(sr * ms / 1000)) / 5).astype(np.float32),
            z(tail_ms),
        ]
    )


def test_words_cover_speech_only() -> None:
    spans = estimate_spans(
        "Hello big world.", tone(1000, lead_ms=200, tail_ms=300), 44100, spaced=True, offset_ms=500
    )
    assert [s.text for s in spans] == ["Hello", "big", "world."]
    assert abs(spans[0].start_ms - 700) <= 15 and abs(spans[-1].end_ms - 1700) <= 15
    assert all(a.end_ms <= b.start_ms for a, b in zip(spans, spans[1:], strict=False))
    assert spans[0].end_ms - spans[0].start_ms > spans[1].end_ms - spans[1].start_ms


def test_japanese_characters() -> None:
    spans = estimate_spans("こんにちは。", tone(600), 44100, spaced=False)
    assert [s.text for s in spans] == list("こんにちは")


def test_japanese_punctuation_pause_extends_previous_character() -> None:
    spans = estimate_spans("あい。う", tone(900), 44100, spaced=False)
    assert [s.text for s in spans] == ["あ", "い", "う"]
    d = [s.end_ms - s.start_ms for s in spans]
    assert d[1] > d[0] and abs(d[0] - d[2]) <= 2


def test_silent_audio_degenerates_gracefully() -> None:
    spans = estimate_spans("Hi there.", np.zeros(4410, np.float32), 44100, spaced=True)
    assert len(spans) == 2 and all(s.end_ms > s.start_ms for s in spans)


def test_empty_audio_and_empty_text() -> None:
    spans = estimate_spans("a b c", np.zeros(0, np.float32), 44100, spaced=True)
    assert all(a.end_ms <= b.start_ms for a, b in zip(spans, spans[1:], strict=False))
    assert all(s.end_ms > s.start_ms for s in spans)
    assert estimate_spans("  ", tone(100), 44100, spaced=True) == []


def test_speech_bounds_trim_silence() -> None:
    start, end = speech_bounds(tone(500, lead_ms=100, tail_ms=100), 44100)
    assert abs(start - 4410) <= 441 and abs(end - 4410 - 22050) <= 441
    assert speech_bounds(np.zeros(1000, np.float32), 44100) == (0, 1000)


def test_deterministic() -> None:
    a = estimate_spans("One, two. Three", tone(800), 44100, spaced=True)
    assert a == estimate_spans("One, two. Three", tone(800), 44100, spaced=True)
