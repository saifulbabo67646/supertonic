"""Shared pytest fixtures."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from supertonic.core import Style

from supertonic_server.voices import VoiceLibrary

if TYPE_CHECKING:
    from supertonic_server.engine import Engine


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


@pytest.fixture
def style() -> Style:
    """A random but valid Supertonic 3 voice style."""
    from fakes import fake_style

    return fake_style()


@pytest.fixture
def engine() -> Engine:
    """An Engine over a FakeModel with a two-worker scheduler."""
    from fakes import FakeModel
    from supertonic_server.engine import Engine, Scheduler

    return Engine(FakeModel(), Scheduler(workers=2, max_queue=64))
