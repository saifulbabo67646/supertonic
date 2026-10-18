"""Test helpers shared across test modules."""

from __future__ import annotations

import json
import tempfile
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
