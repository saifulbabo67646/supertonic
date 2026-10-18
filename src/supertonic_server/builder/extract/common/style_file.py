# Adapted from supertonic.embed (src/style_file.py)
# https://github.com/kdrkdrkdr/supertonic.embed @ 6c38a94af2c429d7f4098708686af80d23ccadc0
# Copyright (c) 2026 Gyeongmin Kim. MIT License (see LICENSE-supertonic-embed).
# Adapted: the preset directory and device are arguments; the style is returned as a dict
# (the worker writes it) and its metadata records only the source file's name; typed.
"""The voice-style file: read, build, presets, and the unit sphere.

A style is two tensors in one JSON, in the format Supertonic ships: ``style_ttl``
[1,50,256] is the timbre, ``style_dp`` [1,8,16] the duration. Every row of both is a unit
vector in the released presets, so an extracted style is projected back to unit rows
after every optimiser step.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import torch

from supertonic_server.builder.extract.common.frozen_tts import SR

TTL_SHAPE = (1, 50, 256)
DP_SHAPE = (1, 8, 16)


def presets_dir(model_dir: Path) -> Path:
    """``<model_dir>/voice_styles``."""
    return model_dir / "voice_styles"


def list_presets(model_dir: Path) -> list[Path]:
    """The shipped presets, ``F1``-``F5`` and ``M1``-``M5``, in name order."""
    found = sorted(presets_dir(model_dir).glob("[FM]*.json"))
    if not found:
        raise FileNotFoundError(f"no preset voice styles in {presets_dir(model_dir)}")
    return found


def preset_path(model_dir: Path, name: str) -> Path:
    """``"M1"`` -> ``<model_dir>/voice_styles/M1.json``."""
    return presets_dir(model_dir) / f"{name}.json"


def load_style(path: Path, device: str | torch.device) -> tuple[torch.Tensor, torch.Tensor]:
    """-> ``(style_ttl, style_dp)`` on ``device``."""
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    ttl, dp = (
        torch.tensor(d[k]["data"], dtype=torch.float32, device=device).reshape(*d[k]["dims"])
        for k in ("style_ttl", "style_dp")
    )
    return ttl, dp


def style_to_json(ttl: torch.Tensor, dp: torch.Tensor, source: str) -> dict[str, Any]:
    """The style as Supertonic ships it, so it drops in beside the presets."""
    return {
        "style_ttl": {
            "data": ttl.detach().reshape(TTL_SHAPE).cpu().numpy().tolist(),
            "dims": list(TTL_SHAPE),
            "type": "float32",
        },
        "style_dp": {
            "data": dp.detach().reshape(DP_SHAPE).cpu().numpy().tolist(),
            "dims": list(DP_SHAPE),
            "type": "float32",
        },
        "metadata": {
            "source_file": Path(source).name or "unknown",
            "source_sample_rate": SR,
            "target_sample_rate": SR,
            "extracted_at": datetime.now(UTC).isoformat(),
        },
    }


def project_to_sphere(style: torch.Tensor) -> None:
    """Put every row back at unit L2 norm, in place."""
    style /= style.norm(dim=-1, keepdim=True).clamp_min(1e-8)
