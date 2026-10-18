"""Pieces both build methods share: frozen Supertonic 3 in torch, presets, style JSON,
reference loading, the nearest-preset scan, the duration-style inversion and the
shared finish. Importing this package imports torch.
"""

from supertonic_server.builder.extract.common.audio import check_readable, load_mono
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
    "style_to_json",
]
