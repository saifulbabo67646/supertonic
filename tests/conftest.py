"""Shared pytest fixtures."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import TYPE_CHECKING

import httpx
import pytest
from supertonic.core import Style

from supertonic_server.api import create_app
from supertonic_server.core.config import Settings
from supertonic_server.voices import VoiceLibrary

if TYPE_CHECKING:
    from fastapi import FastAPI
    from httpx import AsyncClient

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


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """Loopback settings with an isolated data dir and no API key."""
    return Settings(data_dir=tmp_path / "data")


def _client(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


@pytest.fixture
async def client(
    settings: Settings, engine: Engine, lib: VoiceLibrary
) -> AsyncIterator[AsyncClient]:
    """Client for an app without authentication."""
    async with _client(create_app(settings, engine, lib)) as c:
        yield c


@pytest.fixture
async def authed_client(
    settings: Settings, engine: Engine, lib: VoiceLibrary
) -> AsyncIterator[AsyncClient]:
    """Client for an app that requires the API key ``"secret"``."""
    keyed = settings.model_copy(update={"api_key": "secret"})
    async with _client(create_app(keyed, engine, lib)) as c:
        yield c
