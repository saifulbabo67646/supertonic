"""Tests for the app factory, auth, error handlers, system routes and previews."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from pydantic import BaseModel

from supertonic_server import __version__
from supertonic_server.api import AppState, create_app
from supertonic_server.api.deps import preview
from supertonic_server.cli import main
from supertonic_server.core.config import ConfigError, Settings
from supertonic_server.core.errors import ApiError
from supertonic_server.engine import Engine
from supertonic_server.voices import VoiceLibrary


class Body(BaseModel):
    input: str


def _mount_last(app: FastAPI) -> None:
    """Routes added after create_app sit behind the static mount; move the mount to the end."""
    app.router.routes.sort(key=lambda r: getattr(r, "name", "") == "web")


async def test_health_open(client: httpx.AsyncClient) -> None:
    body = (await client.get("/v1/health")).json()
    assert body == {
        "status": "ok",
        "model": "supertonic-3",
        "voices": 2,
        "builder": "none",
        "builder_detail": None,
        "auth": False,
        "version": __version__,
    }


async def test_auth_required(authed_client: httpx.AsyncClient) -> None:
    r = await authed_client.get("/v1/languages")
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "invalid_api_key"
    assert r.json()["error"]["type"] == "authentication_error"
    bad = await authed_client.get("/v1/languages", headers={"Authorization": "Bearer nope"})
    assert bad.status_code == 401
    ok = await authed_client.get("/v1/languages", headers={"Authorization": "Bearer secret"})
    assert ok.status_code == 200 and len(ok.json()["data"]) == 32
    assert set(ok.json()["data"][0]) == {"code", "name", "sample", "spaced"}
    health = await authed_client.get("/v1/health")
    assert health.status_code == 200 and health.json()["auth"] is True


def test_unsafe_config_refuses(tmp_path: Path, engine: Engine, lib: VoiceLibrary) -> None:
    with pytest.raises(ConfigError):
        create_app(Settings(host="0.0.0.0", data_dir=tmp_path), engine, lib)  # noqa: S104


async def test_ui_served_publicly(authed_client: httpx.AsyncClient) -> None:
    r = await authed_client.get("/")
    assert r.status_code == 200 and "<html" in r.text.lower()


async def test_validation_error_shape(
    settings: Settings, engine: Engine, lib: VoiceLibrary
) -> None:
    app = create_app(settings, engine, lib)

    @app.post("/v1/_test")
    async def _route(body: Body) -> dict[str, str]:
        return {"ok": body.input}

    _mount_last(app)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as c:
        r = await c.post("/v1/_test", json={})
    assert r.status_code == 400
    err = r.json()["error"]
    assert err["code"] == "invalid_request" and err["param"] == "input"


async def test_api_error_and_unhandled(
    settings: Settings, engine: Engine, lib: VoiceLibrary
) -> None:
    app = create_app(settings, engine, lib)

    @app.get("/v1/_boom")
    async def _boom() -> None:
        raise RuntimeError("x")

    @app.get("/v1/_api")
    async def _api() -> None:
        raise ApiError(418, "teapot", "short and stout", param="spout")

    _mount_last(app)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as c:
        r = await c.get("/v1/_api")
        assert r.status_code == 418
        assert r.json()["error"] == {
            "message": "short and stout",
            "type": "invalid_request_error",
            "code": "teapot",
            "param": "spout",
        }
        r = await c.get("/v1/_boom")
        assert r.status_code == 500 and r.json()["error"]["code"] == "internal_error"


async def test_preview_renders_once(settings: Settings, engine: Engine, lib: VoiceLibrary) -> None:
    state = AppState(settings, engine, lib)
    calls = 0
    real = engine.render

    async def counting(*a: Any, **k: Any) -> Any:
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.05)
        return await real(*a, **k)

    engine.render = counting  # type: ignore[method-assign]
    paths = await asyncio.gather(preview(state, "F1", "en"), preview(state, "F1", "en"))
    assert paths[0] == paths[1] == lib.preview_path("F1", "en")
    assert paths[0].read_bytes()[:4] == b"RIFF"
    assert calls == 1
    await preview(state, "F1", "en")
    assert calls == 1
    assert not list(paths[0].parent.glob("*.tmp"))


async def test_unknown_and_wrong_method_are_json(client: httpx.AsyncClient) -> None:
    r = await client.get("/v1/nope")
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"
    r = await client.post("/v1/health")
    assert r.status_code == 405 and r.json()["error"]["code"] == "method_not_allowed"


async def test_bearer_scheme_case_insensitive(authed_client: httpx.AsyncClient) -> None:
    r = await authed_client.get("/v1/languages", headers={"Authorization": "bearer secret"})
    assert r.status_code == 200


async def test_preview_rejects_bad_lang(
    settings: Settings, engine: Engine, lib: VoiceLibrary
) -> None:
    state = AppState(settings, engine, lib)
    with pytest.raises(ApiError) as e:
        await preview(state, "F1", "../../x")
    assert e.value.code == "language_not_supported"
    with pytest.raises(ApiError) as e2:
        await preview(state, "nope", "en")
    assert e2.value.code == "voice_not_found"
    assert not (settings.data_dir / "x.wav").exists()
    assert not list(lib.custom_dir.rglob("*.wav")) if lib.custom_dir.exists() else True


def test_one_sided_injection_rejected(settings: Settings, engine: Engine) -> None:
    with pytest.raises(ValueError):
        create_app(settings, engine, None)


def test_cli_exit_2_on_unsafe_config(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as e:
        main(["serve", "--host", "0.0.0.0"])  # noqa: S104
    assert e.value.code == 2
    assert "SUPERTONIC_API_KEY" in capsys.readouterr().err


def test_cli_exit_2_on_invalid_settings(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("SUPERTONIC_MAX_QUEUE", "abc")
    with pytest.raises(SystemExit) as e:
        main(["serve"])
    assert e.value.code == 2
    assert capsys.readouterr().err.startswith("error:")
