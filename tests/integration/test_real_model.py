"""Smoke tests against the real Supertonic 3 weights (downloaded on first run)."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import numpy as np
import pytest

from supertonic_server.core.config import Settings
from supertonic_server.engine import Engine, load_engine
from supertonic_server.text import LANGUAGES
from supertonic_server.voices import VoiceLibrary

pytestmark = pytest.mark.model


@pytest.fixture(scope="module")
def real(tmp_path_factory: pytest.TempPathFactory) -> Iterator[tuple[Engine, VoiceLibrary]]:
    """Load the real engine and a voice library over its preset styles."""
    data_dir = tmp_path_factory.mktemp("data")
    settings = Settings(data_dir=data_dir)
    engine, presets = load_engine(settings)
    yield engine, VoiceLibrary(presets, Path(settings.custom_voices_dir))


@pytest.mark.parametrize(
    ("text", "lang", "voice"),
    [("Hello world. This is Supertonic.", "en", "F1"), ("こんにちは、世界。", "ja", "M1")],
)
async def test_synthesises_audible_audio(
    real: tuple[Engine, VoiceLibrary], text: str, lang: str, voice: str
) -> None:
    engine, library = real
    audio, chunks = await engine.render(text, library.style(voice), lang)
    assert chunks
    assert len(audio) / engine.sample_rate >= 0.5
    assert np.isfinite(audio).all()
    assert float(np.abs(audio).max()) > 0.01


def test_every_language_sample_is_accepted(real: tuple[Engine, VoiceLibrary]) -> None:
    engine, _ = real
    assert len(LANGUAGES) == 32
    for language in LANGUAGES:
        assert engine.prepare(language.sample, language.code), language.code
