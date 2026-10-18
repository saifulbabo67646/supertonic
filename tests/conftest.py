"""Shared pytest fixtures."""

import json
from pathlib import Path

import pytest

from supertonic_server.voices import VoiceLibrary


@pytest.fixture(autouse=True)
def _clean_supertonic_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep host SUPERTONIC_* variables from leaking into tests."""
    import os

    for name in list(os.environ):
        if name.startswith("SUPERTONIC_"):
            monkeypatch.delenv(name)


@pytest.fixture
def lib(tmp_path: Path) -> VoiceLibrary:
    """A VoiceLibrary with preset voices F1 and M1 in a temp dir."""
    from fakes import make_style

    presets = tmp_path / "presets"
    presets.mkdir()
    for vid in ("F1", "M1"):
        (presets / f"{vid}.json").write_text(json.dumps(make_style()), encoding="utf-8")
    return VoiceLibrary(presets, tmp_path / "custom")
