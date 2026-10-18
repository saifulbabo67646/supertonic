"""Shared pytest fixtures."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import AbstractContextManager
from pathlib import Path
from typing import TYPE_CHECKING, Any

import anyio
import httpx
import pytest
from starlette.testclient import TestClient, WebSocketTestSession
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
    """Keep host SUPERTONIC_* variables and the developer's ./.env out of tests."""
    import os

    for name in list(os.environ):
        if name.startswith("SUPERTONIC_"):
            monkeypatch.delenv(name)
    monkeypatch.setitem(Settings.model_config, "env_file", None)


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


def make_client(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


@pytest.fixture
def app_client() -> Callable[[FastAPI], httpx.AsyncClient]:
    """Factory wrapping an app in an in-process ``httpx.AsyncClient``."""
    return make_client


@pytest.fixture
async def client(
    settings: Settings, engine: Engine, lib: VoiceLibrary
) -> AsyncIterator[AsyncClient]:
    """Client for an app without authentication."""
    async with make_client(create_app(settings, engine, lib)) as c:
        yield c


@pytest.fixture
async def authed_client(
    settings: Settings, engine: Engine, lib: VoiceLibrary
) -> AsyncIterator[AsyncClient]:
    """Client for an app that requires the API key ``"secret"``."""
    keyed = settings.model_copy(update={"api_key": "secret"})
    async with make_client(create_app(keyed, engine, lib)) as c:
        yield c


WS_PATH = "/v1/audio/speech/websocket"
WsFactory = Callable[[str], AbstractContextManager[WebSocketTestSession]]


def recv_json(ws: WebSocketTestSession, timeout: float = 5.0) -> dict[str, Any]:
    """Receive one JSON message, failing the test instead of hanging after ``timeout`` s."""

    async def receive() -> Any:
        with anyio.fail_after(timeout):
            # Private attribute: TestClient's own receive() has no timeout.
            return await ws._send_rx.receive()

    message = ws.portal.call(receive)
    if message["type"] == "websocket.close":
        raise AssertionError(f"socket closed: {message}")
    data: dict[str, Any] = json.loads(message["text"])
    return data


def recv_until(ws: WebSocketTestSession, type_: str, timeout: float = 5.0) -> list[dict[str, Any]]:
    """Collect messages up to and including the first one of type ``type_``."""
    msgs: list[dict[str, Any]] = []
    while True:
        msgs.append(recv_json(ws, timeout))
        if msgs[-1]["type"] == type_:
            return msgs


def _ws_factory(app: FastAPI) -> WsFactory:
    client = TestClient(app)
    return lambda query: client.websocket_connect(WS_PATH + query)


@pytest.fixture
def client_ws_factory(settings: Settings, engine: Engine, lib: VoiceLibrary) -> WsFactory:
    """Open WebSockets (``factory("?voice=M1")``) on an app without authentication."""
    return _ws_factory(create_app(settings, engine, lib))


@pytest.fixture
def authed_ws_factory(settings: Settings, engine: Engine, lib: VoiceLibrary) -> WsFactory:
    """Open WebSockets on an app that requires the API key ``"secret"``."""
    keyed = settings.model_copy(update={"api_key": "secret"})
    return _ws_factory(create_app(keyed, engine, lib))


@pytest.fixture
def ws(client_ws_factory: WsFactory) -> Iterator[WebSocketTestSession]:
    """A connected realtime WebSocket (``session.created`` not yet read)."""
    with client_ws_factory("") as sock:
        yield sock


@pytest.fixture
def ws_slow(settings: Settings, lib: VoiceLibrary) -> Iterator[WebSocketTestSession]:
    """A realtime WebSocket whose FakeModel sleeps 0.1 s per sentence."""
    from fakes import FakeModel
    from supertonic_server.engine import Engine, Scheduler

    slow = Engine(FakeModel(delay=0.1), Scheduler(workers=2, max_queue=64))
    with _ws_factory(create_app(settings, slow, lib))("") as sock:
        yield sock
