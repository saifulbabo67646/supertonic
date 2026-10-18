"""The synthesis model interface and loading the real Supertonic 3 engine."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

import numpy as np
from supertonic.core import Style

from supertonic_server.core.config import Settings

if TYPE_CHECKING:
    from supertonic_server.engine.engine import Engine

logger = logging.getLogger(__name__)


class TextProcessor(Protocol):
    """Reports which characters of a text the model cannot render."""

    def validate_text(self, text: str) -> tuple[bool, list[str]]:
        """Return ``(all_supported, unsupported_characters)``."""
        ...


class SynthModel(Protocol):
    """What the engine needs from a model; ``supertonic.TTS(...).model`` satisfies it."""

    sample_rate: int
    text_processor: TextProcessor

    def __call__(
        self,
        text_list: list[str],
        style: Style,
        total_step: int,
        speed: float,
        lang: str | None,
    ) -> tuple[np.ndarray, np.ndarray]:
        """Synthesize ``text_list``; returns waveforms ``(batch, n)`` and durations (s)."""
        ...


def load_engine(settings: Settings) -> tuple[Engine, Path]:
    """Load Supertonic 3 (downloading weights if needed) and build an :class:`Engine`.

    Returns:
        The engine and the directory holding the preset voice styles.
    """
    import supertonic

    from supertonic_server.engine.engine import Engine
    from supertonic_server.engine.scheduler import Scheduler

    tts = supertonic.TTS(
        model="supertonic-3",
        model_dir=settings.model_dir,
        auto_download=True,
        intra_op_num_threads=settings.intra_op_threads,
    )
    workers = settings.effective_workers()
    logger.info("loaded supertonic-3 from %s (%d workers)", tts.model_dir, workers)
    scheduler = Scheduler(workers=workers, max_queue=settings.max_queue)
    return Engine(tts.model, scheduler), Path(tts.model_dir) / "voice_styles"
