"""Tests for the native voices API."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from fakes import make_style

if TYPE_CHECKING:
    from httpx import AsyncClient

    from supertonic_server.engine import Engine


async def test_import_list_export_delete(client: AsyncClient) -> None:
    r = await client.post(
        "/v1/voices/import", json={"style": make_style(), "name": "Narrator", "source_note": "me"}
    )
    assert r.status_code == 201
    vid = r.json()["id"]
    listed = (await client.get("/v1/voices?kind=custom")).json()["data"]
    assert vid in [v["id"] for v in listed]
    assert listed[0]["preview_url"] == f"/v1/voices/{vid}/preview"
    exp = await client.get(f"/v1/voices/{vid}/style")
    assert exp.json()["style_ttl"]["dims"] == [1, 50, 256]
    assert exp.headers["content-disposition"] == f'attachment; filename="{vid}.json"'
    assert (await client.get(f"/v1/voices/{vid}")).json()["name"] == "Narrator"
    assert (await client.delete(f"/v1/voices/{vid}")).status_code == 204
    assert (await client.get(f"/v1/voices/{vid}")).status_code == 404


async def test_import_invalid_style(client: AsyncClient) -> None:
    r = await client.post("/v1/voices/import", json={"style": {"style_ttl": {}}, "name": "x"})
    assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_style"


async def test_import_requires_name(client: AsyncClient) -> None:
    r = await client.post("/v1/voices/import", json={"style": make_style(), "name": "  "})
    assert r.status_code == 400 and r.json()["error"]["param"] == "name"


async def test_import_multipart(client: AsyncClient) -> None:
    files = {"file": ("v.json", json.dumps(make_style()), "application/json")}
    data = {"name": "Multi", "tags": "a, b ,,c", "description": "d"}
    r = await client.post("/v1/voices/import", files=files, data=data)
    assert r.status_code == 201
    assert r.json()["tags"] == ["a", "b", "c"] and r.json()["description"] == "d"


async def test_import_multipart_missing_file(client: AsyncClient) -> None:
    r = await client.post("/v1/voices/import", data={"name": "x"}, files={"other": ("o", "x")})
    assert r.status_code == 400 and r.json()["error"]["param"] == "file"


async def test_import_too_large(client: AsyncClient) -> None:
    big = {"style": make_style(), "name": "Big", "source_note": "x" * (2 * 1024 * 1024)}
    r = await client.post("/v1/voices/import", json=big)
    assert r.status_code == 413 and r.json()["error"]["code"] == "payload_too_large"
    files = {"file": ("v.json", b" " * (2 * 1024 * 1024 + 1), "application/json")}
    r = await client.post("/v1/voices/import", files=files, data={"name": "Big"})
    assert r.status_code == 413


async def test_import_bad_json(client: AsyncClient) -> None:
    r = await client.post(
        "/v1/voices/import", content=b"{nope", headers={"content-type": "application/json"}
    )
    assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_request"


async def test_list_filters(client: AsyncClient) -> None:
    await client.post(
        "/v1/voices/import", json={"style": make_style(), "name": "T", "tags": ["warm"]}
    )
    presets = (await client.get("/v1/voices?kind=preset")).json()["data"]
    assert {v["id"] for v in presets} == {"F1", "M1"}
    tagged = (await client.get("/v1/voices?tag=warm")).json()["data"]
    assert [v["name"] for v in tagged] == ["T"]
    bad = await client.get("/v1/voices?kind=other")
    assert bad.status_code == 400 and bad.json()["error"]["param"] == "kind"


async def test_patch(client: AsyncClient) -> None:
    vid = (
        await client.post("/v1/voices/import", json={"style": make_style(), "name": "P"})
    ).json()["id"]
    r = await client.patch(f"/v1/voices/{vid}", json={"name": " New ", "tags": ["x"]})
    assert r.status_code == 200 and r.json()["name"] == "New" and r.json()["tags"] == ["x"]
    for body, param in (({"name": "  "}, "name"), ({"tags": ["ok", " "]}, "tags")):
        bad = await client.patch(f"/v1/voices/{vid}", json=body)
        assert bad.status_code == 400 and bad.json()["error"]["param"] == param
    assert (await client.patch("/v1/voices/F1", json={"name": "z"})).status_code == 400
    assert (await client.patch("/v1/voices/nope", json={"name": "z"})).status_code == 404


async def test_delete_preset_refused(client: AsyncClient) -> None:
    r = await client.delete("/v1/voices/F1")
    assert r.status_code == 400 and r.json()["error"]["code"] == "voice_read_only"


async def test_preview_cached(client: AsyncClient, engine: Engine) -> None:
    a = await client.get("/v1/voices/F1/preview?language=ja")
    calls = len(engine.model.calls)  # type: ignore[attr-defined]
    b = await client.get("/v1/voices/F1/preview?language=ja")
    assert a.headers["content-type"] == "audio/wav"
    assert a.content[:4] == b"RIFF" and a.content == b.content
    assert len(engine.model.calls) == calls  # type: ignore[attr-defined]


async def test_preview_validation(client: AsyncClient) -> None:
    assert (await client.get("/v1/voices/F1/preview?language=xx")).status_code == 400
    assert (await client.get("/v1/voices/zz/preview")).status_code == 404


async def test_voices_require_key(authed_client: AsyncClient) -> None:
    assert (await authed_client.get("/v1/voices")).status_code == 401
