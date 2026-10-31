"""Pieces both build methods share: frozen Supertonic 3 in torch, presets, style JSON,
reference loading, pitch, the nearest-preset scan, the duration-style inversion and the
shared finish.

The names below load their module on first use, so importing this package (or the pure
numpy :mod:`.pitch` module) does not import torch; most of the modules do.
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from supertonic_server.builder.extract.common.audio import (
        check_readable,
        load_mono,
        reference_f0,
    )
    from supertonic_server.builder.extract.common.duration import duration_inversion
    from supertonic_server.builder.extract.common.finish import finish_with_duration
    from supertonic_server.builder.extract.common.frozen_tts import (
        SR,
        FrozenTTS,
        Prompt,
        load_frozen_tts,
    )
    from supertonic_server.builder.extract.common.preset_scan import WaveLoss, nearest_preset
    from supertonic_server.builder.extract.common.style_file import (
        DP_SHAPE,
        TTL_SHAPE,
        list_presets,
        load_style,
        preset_path,
        project_to_sphere,
        style_to_json,
    )
    from supertonic_server.builder.extract.duration_config import DurationConfig

_HOMES = {
    "audio": ("check_readable", "load_mono", "reference_f0"),
    "duration": ("duration_inversion",),
    "finish": ("finish_with_duration",),
    "frozen_tts": ("SR", "FrozenTTS", "Prompt", "load_frozen_tts"),
    "preset_scan": ("WaveLoss", "nearest_preset"),
    "style_file": (
        "DP_SHAPE",
        "TTL_SHAPE",
        "list_presets",
        "load_style",
        "preset_path",
        "project_to_sphere",
        "style_to_json",
    ),
}
_WHERE = {
    name: f"supertonic_server.builder.extract.common.{module}"
    for module, names in _HOMES.items()
    for name in names
}
_WHERE["DurationConfig"] = "supertonic_server.builder.extract.duration_config"

__all__ = [
    "DP_SHAPE",
    "SR",
    "TTL_SHAPE",
    "DurationConfig",
    "FrozenTTS",
    "Prompt",
    "WaveLoss",
    "check_readable",
    "duration_inversion",
    "finish_with_duration",
    "list_presets",
    "load_frozen_tts",
    "load_mono",
    "load_style",
    "nearest_preset",
    "preset_path",
    "project_to_sphere",
    "reference_f0",
    "style_to_json",
]


def __getattr__(name: str) -> Any:
    """Import the module that defines ``name`` on first access."""
    module = _WHERE.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(importlib.import_module(module), name)
    globals()[name] = value
    return value
