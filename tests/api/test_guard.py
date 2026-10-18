"""Tests for the ASGI guard: API key, forwarded-header check and body cap (I6, I10, M3)."""

from __future__ import annotations

import itertools
import json
from collections.abc import AsyncIterator, Iterable
from typing import TYPE_CHECKING, Any

import httpx
import pytest
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from conftest import WS_PATH
from supertonic_server.api import create_app
from supertonic_server.api.guard import MAX_BODY_BYTES, MAX_IMPORT_BODY_BYTES

if TYPE_CHECKING:
    from fastapi import FastAPI

    from supertonic_server.core.config import Settings
    from supertonic_server.engine import Engine
    from supertonic_server.voices import VoiceLibrary

KEY = {"Authorization": "Bearer secret"}
CHUNK = 64 * 1024


async def asgi_post(
    app: FastAPI, path: str, chunks: Iterable[bytes], headers: dict[str, str] | None = None
) -> tuple[int, dict[str, Any], int]:
    """POST ``chunks`` as a streamed body; return status, JSON body and bytes consumed."""
    consumed = 0
    it = iter(chunks)
    sent: list[dict[str, Any]] = []

    async def receive() -> dict[str, Any]:
        nonlocal consumed
        body = next(it, None)
        if body is None:
            return {"type": "http.request", "body": b"", "more_body": False}
        consumed += len(body)
        return {"type": "http.request", "body": body, "more_body": True}

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    hdrs = {"content-type": "application/json", **(headers or {})}
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": [(k.lower().encode(), v.encode()) for k, v in hdrs.items()],
        "client": ("127.0.0.1", 50000),
        "server": ("test", 80),
    }
    await app(scope, receive, send)
    start = next(m for m in sent if m["type"] == "http.response.start")
    body = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    return start["status"], json.loads(body), consumed


@pytest.fixture
def app(settings: Settings, engine: Engine, lib: VoiceLibrary) -> FastAPI:
    return create_app(settings, engine, lib)


@pytest.fixture
def keyed_app(settings: Settings, engine: Engine, lib: VoiceLibrary) -> FastAPI:
    return create_app(settings.model_copy(update={"api_key": "secret"}), engine, lib)


async def test_auth_runs_before_body_parsing(authed_client: httpx.AsyncClient) -> None:
    r = await authed_client.post(
        "/v1/audio/speech", content=b"{not json", headers={"content-type": "application/json"}
    )
    assert r.status_code == 401 and r.json()["error"]["code"] == "invalid_api_key"


async def test_unauthenticated_big_body_not_read(keyed_app: FastAPI) -> None:
    status, body, consumed = await asgi_post(keyed_app, "/v1/audio/speech", itertools.repeat(b"x"))
    assert status == 401 and consumed == 0 and body["error"]["code"] == "invalid_api_key"


async def test_streamed_oversized_body_is_cut_off(app: FastAPI) -> None:
    chunks = itertools.repeat(b" " * CHUNK)  # endless chunked body, no Content-Length
    status, body, consumed = await asgi_post(app, "/v1/audio/speech", chunks)
    assert status == 413 and body["error"]["code"] == "payload_too_large"
    assert consumed <= MAX_BODY_BYTES + CHUNK


async def test_declared_oversized_body_rejected_unread(app: FastAPI) -> None:
    headers = {"content-length": str(MAX_BODY_BYTES + 1)}
    status, body, consumed = await asgi_post(app, "/v1/tts/timestamps", [b"x"], headers)
    assert status == 413 and consumed == 0 and body["error"]["code"] == "payload_too_large"


async def test_import_gets_a_larger_allowance(app: FastAPI) -> None:
    under = [b" " * CHUNK] * ((MAX_BODY_BYTES * 3 // 2) // CHUNK)  # 1.5 MB of whitespace
    status, body, _ = await asgi_post(app, "/v1/voices/import", under)
    assert status == 400 and body["error"]["code"] == "invalid_request"  # parsed, not capped
    over = itertools.repeat(b" " * CHUNK)
    status, body, consumed = await asgi_post(app, "/v1/voices/import", over)
    assert status == 413 and consumed <= MAX_IMPORT_BODY_BYTES + CHUNK


async def test_chunked_body_within_limit_works(authed_client: httpx.AsyncClient) -> None:
    payload = json.dumps({"input": "Hi.", "voice": "F1", "response_format": "pcm"}).encode()

    async def gen() -> AsyncIterator[bytes]:
        for i in range(0, len(payload), 7):
            yield payload[i : i + 7]

    headers = {"content-type": "application/json", **KEY}
    r = await authed_client.post("/v1/audio/speech", content=gen(), headers=headers)
    assert r.status_code == 200 and len(r.content) > 0


async def test_health_public_but_other_methods_and_paths_not(
    authed_client: httpx.AsyncClient,
) -> None:
    assert (await authed_client.get("/v1/health")).status_code == 200
    assert (await authed_client.post("/v1/health")).status_code == 401
    assert (await authed_client.get("/v1/nope")).status_code == 401
    assert (await authed_client.get("/v1/nope", headers=KEY)).status_code == 404


@pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json"])
async def test_docs_require_key_when_set(
    authed_client: httpx.AsyncClient, client: httpx.AsyncClient, path: str
) -> None:
    assert (await authed_client.get(path)).status_code == 401
    assert (await authed_client.get(path, headers=KEY)).status_code == 200
    assert (await client.get(path)).status_code == 200


@pytest.mark.parametrize(
    "header", ["CF-Connecting-IP", "X-Forwarded-For", "Forwarded", "X-Real-IP"]
)
async def test_forwarded_without_key_refused(
    client: httpx.AsyncClient, authed_client: httpx.AsyncClient, header: str
) -> None:
    for path in ("/v1/health", "/v1/languages", "/"):
        r = await client.get(path, headers={header: "203.0.113.7"})
        assert r.status_code == 403
        err = r.json()["error"]
        assert err["code"] == "forwarded_without_key" and "SUPERTONIC_API_KEY" in err["message"]
    ok = await authed_client.get("/v1/languages", headers={header: "203.0.113.7", **KEY})
    assert ok.status_code == 200


def test_forwarded_websocket_without_key_refused(app: FastAPI) -> None:
    headers = {"X-Forwarded-For": "203.0.113.7"}
    with TestClient(app).websocket_connect(WS_PATH, headers=headers) as ws:
        m = ws.receive_json()
        assert m["type"] == "conversation.item.tts.failed"
        assert m["error"]["code"] == "forwarded_without_key"
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
        assert exc.value.code == 1008


def test_websocket_bad_key_still_explained(keyed_app: FastAPI) -> None:
    with TestClient(keyed_app).websocket_connect(WS_PATH + "?api_key=wrong") as ws:
        assert ws.receive_json()["error"]["code"] == "invalid_api_key"
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
        assert exc.value.code == 1008
    with TestClient(keyed_app).websocket_connect(WS_PATH, headers=KEY) as ws:
        assert ws.receive_json()["type"] == "session.created"
