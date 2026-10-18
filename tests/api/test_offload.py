"""CPU-heavy steps of HTTP handlers must not run on the event loop (I4).

Each test swaps a step for a probe that blocks until a coroutine on the event loop releases
it. Run on the loop thread, the probe would block the loop, the release could never happen
and the probe would report a timeout; run in a worker thread it is released at once.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

import pytest

from supertonic_server.api import AppState
from supertonic_server.api.deps import preview
from supertonic_server.api.routes import openai_speech, timestamps

if TYPE_CHECKING:
    from httpx import AsyncClient

    from supertonic_server.core.config import Settings
    from supertonic_server.engine import Engine
    from supertonic_server.voices import VoiceLibrary


class Probe:
    """Wraps ``fn``; records whether the loop stayed free while it ran."""

    def __init__(self, fn: Callable[..., Any]) -> None:
        self.fn = fn
        self.started = threading.Event()
        self.released = threading.Event()
        self.loop_was_free: bool | None = None

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        self.started.set()
        self.loop_was_free = self.released.wait(timeout=3)
        return self.fn(*args, **kwargs)

    async def release_when_started(self) -> None:
        # The wait happens in a thread; only the release needs the event loop.
        if await asyncio.to_thread(self.started.wait, 3):
            self.released.set()


async def _run_with(probe: Probe, work: Any) -> Any:
    releaser = asyncio.create_task(probe.release_when_started())
    try:
        return await work
    finally:
        releaser.cancel()


async def test_mp3_encode_off_loop(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    probe = Probe(openai_speech.encode)
    monkeypatch.setattr(openai_speech, "encode", probe)
    body = {"input": "Hello there. Bye.", "voice": "F1", "response_format": "mp3"}
    r = await _run_with(probe, client.post("/v1/audio/speech", json=body))
    assert r.status_code == 200 and probe.loop_was_free is True


async def test_pcm_conversion_off_loop(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    probe = Probe(openai_speech.to_pcm16)
    monkeypatch.setattr(openai_speech, "to_pcm16", probe)
    body = {"input": "Hello there.", "voice": "F1", "response_format": "pcm"}
    r = await _run_with(probe, client.post("/v1/audio/speech", json=body))
    assert r.status_code == 200 and probe.loop_was_free is True


async def test_timestamps_encode_off_loop(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    probe = Probe(timestamps.encode)
    monkeypatch.setattr(timestamps, "encode", probe)
    body = {"text": "Hello there.", "voice": "F1"}
    r = await _run_with(probe, client.post("/v1/tts/timestamps", json=body))
    assert r.status_code == 200 and probe.loop_was_free is True


async def test_preview_write_off_loop(
    settings: Settings, engine: Engine, lib: VoiceLibrary, monkeypatch: pytest.MonkeyPatch
) -> None:
    probe = Probe(lib.save_preview)
    monkeypatch.setattr(lib, "save_preview", probe)
    path = await _run_with(probe, preview(AppState(settings, engine, lib), "F1", "en"))
    assert path.exists() and probe.loop_was_free is True


async def test_prepare_off_loop(client: AsyncClient, engine: Engine) -> None:
    probe = Probe(engine.prepare)
    engine.prepare = probe  # type: ignore[method-assign]
    body = {"input": "Hello there. " * 100, "voice": "F1", "response_format": "pcm"}
    r = await _run_with(probe, client.post("/v1/audio/speech", json=body))
    assert r.status_code == 200 and probe.loop_was_free is True
