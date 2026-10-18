"""Test helpers shared across test modules."""

from __future__ import annotations

import json
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

import numpy as np
from supertonic.core import Style
from supertonic.loader import load_voice_style_from_json_file


def make_style(seed: int = 0) -> dict[str, Any]:
    """Build a valid Supertonic 3 style document (nested ``data`` lists)."""
    rng = np.random.default_rng(seed)

    def part(dims: list[int]) -> dict[str, Any]:
        arr = rng.standard_normal(dims).astype("float32")
        return {"data": arr.tolist(), "dims": dims, "type": "float32"}

    return {
        "style_ttl": part([1, 50, 256]),
        "style_dp": part([1, 8, 16]),
        "metadata": {"seed": seed},
    }


def fake_style(seed: int = 0) -> Style:
    """Build a ``supertonic.core.Style`` through the real loader."""
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "style.json"
        path.write_text(json.dumps(make_style(seed)), encoding="utf-8")
        return load_voice_style_from_json_file(path)


class _FakeTextProcessor:
    """Reports the characters in ``unsupported`` as unrenderable."""

    def __init__(self, unsupported: str) -> None:
        self.unsupported = unsupported

    def validate_text(self, text: str) -> tuple[bool, list[str]]:
        bad = sorted({ch for ch in text if ch in self.unsupported})
        return (not bad, bad)


class FakeModel:
    """Stand-in for ``supertonic.core.Supertonic``.

    Returns a 440 Hz sine lasting ``0.05 s × len(text) / speed`` plus a padded tail (the real
    vocoder output is also longer than the reported duration), records every call in
    ``calls`` and sleeps ``delay`` seconds per call so scheduling can be observed.
    """

    PAD = 1000

    def __init__(
        self, sample_rate: int = 44100, delay: float = 0.0, unsupported: str = "😀★"
    ) -> None:
        self.sample_rate = sample_rate
        self.delay = delay
        self.text_processor = _FakeTextProcessor(unsupported)
        self.calls: list[tuple[list[str], Style, int, float, str | None]] = []
        self._lock = threading.Lock()

    def __call__(
        self,
        text_list: list[str],
        style: Style,
        total_step: int = 5,
        speed: float = 1.05,
        lang: str | None = None,
    ) -> tuple[np.ndarray, np.ndarray]:
        with self._lock:
            self.calls.append((list(text_list), style, total_step, speed, lang))
        if self.delay:
            time.sleep(self.delay)
        dur = 0.05 * len(text_list[0]) / speed
        n = int(dur * self.sample_rate) + self.PAD
        t = np.arange(n, dtype=np.float32) / self.sample_rate
        wav = (0.5 * np.sin(2 * np.pi * 440.0 * t)).astype(np.float32)[None, :]
        return wav, np.array([dur], dtype=np.float32)
