"""Tests for the OpenAI-compatible speech endpoint and /v1/models."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections.abc import AsyncGenerator
from typing import TYPE_CHECKING, Any

import httpx
import numpy as np
import openai
import pytest

from supertonic_server.api import create_app
from supertonic_server.api.routes.openai_speech import _body
from supertonic_server.engine import PRIORITY_DEFAULT, PRIORITY_REALTIME, Engine

if TYPE_CHECKING:
    from httpx import AsyncClient

    from supertonic_server.core.config import Settings
    from supertonic_server.voices import VoiceLibrary


async def test_validation_error_shape(client: AsyncClient) -> None:
    r = await client.post("/v1/audio/speech", json={"voice": "F1"})
    assert r.status_code == 400
    assert r.json()["error"]["param"] == "input"


async def test_requires_auth(authed_client: AsyncClient) -> None:
    r = await authed_client.post("/v1/audio/speech", json={"input": "Hi.", "voice": "F1"})
    assert r.status_code == 401
    assert (await authed_client.get("/v1/models")).status_code == 401


async def test_models(client: AsyncClient) -> None:
    r = await client.get("/v1/models")
    assert r.json() == {
        "object": "list",
        "data": [{"id": "supertonic-3", "object": "model", "owned_by": "supertone"}],
    }


async def test_pcm_streams_24k(client: AsyncClient) -> None:
    async with client.stream(
        "POST",
        "/v1/audio/speech",
        json={"input": "One. Two.", "voice": "F1", "response_format": "pcm"},
    ) as r:
        assert (
            r.status_code == 200
            and r.headers["content-type"] == "audio/pcm"
            and r.headers["x-sample-rate"] == "24000"
        )
        parts = [p async for p in r.aiter_bytes()]
    assert sum(map(len, parts)) % 2 == 0 and sum(map(len, parts)) > 0


async def test_wav_streaming_header_and_rate(client: AsyncClient) -> None:
    r = await client.post(
        "/v1/audio/speech",
        json={"input": "Hi.", "voice": "F1", "response_format": "wav", "sample_rate": 16000},
    )
    assert r.content[:4] == b"RIFF" and r.content[8:12] == b"WAVE"
    assert int.from_bytes(r.content[24:28], "little") == 16000
    assert r.headers["x-sample-rate"] == "16000"


async def test_mp3_default_and_voice_by_name(client: AsyncClient) -> None:
    r = await client.post(
        "/v1/audio/speech", json={"model": "tts-1", "input": "Hello.", "voice": "f1"}
    )
    assert (
        r.status_code == 200
        and r.headers["content-type"] == "audio/mpeg"
        and r.headers["x-voice-id"] == "F1"
        and len(r.content) > 100
    )


async def test_unspeakable_characters_are_dropped(client: AsyncClient, engine: Engine) -> None:
    r = await client.post(
        "/v1/audio/speech",
        json={"input": "Hi \U0001f600 there.", "voice": "F1", "response_format": "pcm"},
    )
    assert r.status_code == 200
    assert "\U0001f600" not in engine.model.calls[0][0][0]  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    ("body", "code"),
    [
        ({"voice": "nobody"}, "voice_not_found"),
        ({"speed": 3.0}, "invalid_speed"),
        ({"total_steps": 0}, "invalid_total_steps"),
        ({"language": "xx"}, "language_not_supported"),
        ({"input": "\U0001f600"}, "empty_input"),
        ({"input": "a" * 100_001}, "input_too_long"),
        ({"sample_rate": 8000, "response_format": "pcm"}, "invalid_sample_rate"),
        ({"response_format": "mp3", "speed": 0.1}, "invalid_speed"),
    ],
)
async def test_errors_are_json_before_stream(
    client: AsyncClient, body: dict[str, Any], code: str
) -> None:
    payload = {"input": "Hi.", "voice": "F1", "response_format": "pcm", **body}
    r = await client.post("/v1/audio/speech", json=payload)
    assert r.status_code in (400, 404) and r.json()["error"]["code"] == code


async def test_long_input_streams_over_http(client: AsyncClient) -> None:
    """Long input is accepted and fully streamed.

    httpx's ASGITransport buffers the whole body, so the "first bytes arrive early"
    property is asserted on the body generator in the next test instead.
    """
    text = "This is a sentence. " * 200
    r = await client.post(
        "/v1/audio/speech", json={"input": text, "voice": "F1", "response_format": "pcm"}
    )
    assert r.status_code == 200 and len(r.content) > 100_000


async def test_body_generator_streams_and_closes_engine(engine: Engine, lib: VoiceLibrary) -> None:
    """First bytes need only the first sentences; closing the body stops the engine stream."""
    text = "This is a sentence. " * 1000
    chunks = engine.stream(text, lib.style("F1"), "en")
    first = await anext(chunks)
    body = _body(first, chunks, engine.sample_rate, 24000, header=True)
    assert (await anext(body)).startswith(b"RIFF")
    assert len(await anext(body)) > 0
    assert len(engine.model.calls) <= 3  # type: ignore[attr-defined]
    await body.aclose()
    seen = len(engine.model.calls)  # type: ignore[attr-defined]
    await asyncio.sleep(0.2)
    assert len(engine.model.calls) == seen  # type: ignore[attr-defined]
    assert chunks.ag_frame is None  # engine generator finished


async def test_openai_sdk_compat(settings: Settings, engine: Engine, lib: VoiceLibrary) -> None:
    app = create_app(settings, engine, lib)
    http = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
    async with http:
        sdk = openai.AsyncOpenAI(base_url="http://test/v1", api_key="x", http_client=http)
        resp = await sdk.audio.speech.create(
            model="tts-1", voice="M1", input="Hi.", response_format="wav"
        )
        assert resp.content.startswith(b"RIFF")


@pytest.mark.parametrize(
    ("extra", "steps", "priority"),
    [
        ({"response_format": "pcm"}, 3, PRIORITY_REALTIME),  # settings.realtime_steps
        ({"response_format": "pcm", "total_steps": 5}, 5, PRIORITY_REALTIME),
        ({"response_format": "wav"}, 8, PRIORITY_DEFAULT),
        ({"response_format": "mp3"}, 8, PRIORITY_DEFAULT),
    ],
)
async def test_pcm_is_the_realtime_path(
    client: AsyncClient,
    engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
    extra: dict[str, Any],
    steps: int,
    priority: int,
) -> None:
    """``pcm`` (the live-agent path) runs at realtime priority and realtime steps (I5b)."""
    seen: list[int] = []
    real_submit = engine.scheduler.submit

    async def submit(fn: Any, prio: int) -> Any:
        seen.append(prio)
        return await real_submit(fn, prio)

    monkeypatch.setattr(engine.scheduler, "submit", submit)
    r = await client.post("/v1/audio/speech", json={"input": "Hi.", "voice": "F1", **extra})
    assert r.status_code == 200
    assert [c[2] for c in engine.model.calls] == [steps]  # type: ignore[attr-defined]
    assert seen == [priority]


@pytest.mark.parametrize(("fmt", "status"), [("mp3", 400), ("flac", 400), ("pcm", 200)])
async def test_render_formats_are_capped(client: AsyncClient, fmt: str, status: int) -> None:
    text = "Hello there. " * 1600  # 20 800 characters
    body = {"input": text, "voice": "F1", "response_format": fmt}
    r = await client.post("/v1/audio/speech", json=body)
    assert r.status_code == status
    if status == 400:
        err = r.json()["error"]
        assert err["code"] == "input_too_long" and "pcm" in err["message"]


async def test_mid_stream_failure_is_logged_and_truncates(
    engine: Engine, lib: VoiceLibrary, caplog: pytest.LogCaptureFixture
) -> None:
    """A failure after the first bytes ends the body with a warning, not an error (D3)."""
    from supertonic_server.engine import Chunk

    async def failing() -> AsyncGenerator[Chunk, None]:
        raise RuntimeError("model fell over")
        yield  # pragma: no cover

    first = Chunk("Hi.", np.zeros(100, dtype=np.float32))
    parts = [p async for p in _body(first, failing(), 44100, 24000, header=False)]
    assert len(parts) == 1
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert warnings and "truncated" in warnings[0].getMessage()
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]


@pytest.mark.parametrize("spec_version", ["2.3", "2.4"])
async def test_early_disconnect_closes_engine_stream(
    settings: Settings, lib: VoiceLibrary, monkeypatch: pytest.MonkeyPatch, spec_version: str
) -> None:
    """A client leaving while a chunk is being sent stops the lookahead at once (D3)."""
    from fakes import FakeModel
    from supertonic_server.engine import Scheduler

    engine = Engine(FakeModel(delay=0.02), Scheduler(workers=1, max_queue=64))
    streams: list[Any] = []
    real_stream = engine.stream

    def capture(*a: Any, **k: Any) -> Any:
        streams.append(real_stream(*a, **k))
        return streams[-1]

    monkeypatch.setattr(engine, "stream", capture)
    app = create_app(settings, engine, lib)
    body = json.dumps({"input": "Sentence. " * 50, "voice": "F1", "response_format": "pcm"})
    first_sent = asyncio.Event()
    requested = False

    async def receive() -> dict[str, Any]:
        nonlocal requested
        if not requested:
            requested = True
            return {"type": "http.request", "body": body.encode(), "more_body": False}
        await first_sent.wait()
        return {"type": "http.disconnect"}

    bodies = 0

    async def send(message: dict[str, Any]) -> None:
        nonlocal bodies
        if message["type"] != "http.response.body":
            return
        bodies += 1
        if bodies == 1:
            first_sent.set()
            return
        if spec_version == "2.4":
            raise OSError("client gone")
        await asyncio.Event().wait()  # a stuck socket; cancelled on disconnect

    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": spec_version},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/v1/audio/speech",
        "raw_path": b"/v1/audio/speech",
        "query_string": b"",
        "root_path": "",
        "headers": [(b"content-type", b"application/json")],
        "client": ("127.0.0.1", 1),
        "server": ("test", 80),
    }
    with contextlib.suppress(Exception):
        await app(scope, receive, send)
    assert streams and streams[0].ag_frame is None  # engine generator finished
    assert engine.scheduler.waiting == 0
    assert len(engine.model.calls) < 10  # type: ignore[attr-defined]
