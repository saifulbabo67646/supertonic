"""Tests for the native voices API."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from fakes import make_style

if TYPE_CHECKING:
    from httpx import AsyncClient

    from supertonic_server.engine import Engine
    from supertonic_server.voices import VoiceLibrary


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


async def test_import_name_too_long(client: AsyncClient) -> None:
    body = {"style": make_style(), "name": "n" * 101}
    r = await client.post("/v1/voices/import", json=body)
    assert r.status_code == 400 and r.json()["error"]["param"] == "name"
    ok = await client.post("/v1/voices/import", json={**body, "name": "n" * 100})
    assert ok.status_code == 201
    r = await client.patch(f"/v1/voices/{ok.json()['id']}", json={"name": "n" * 101})
    assert r.status_code == 400 and r.json()["error"]["param"] == "name"


async def test_preview_of_voice_deleted_mid_render(
    client: AsyncClient, engine: Engine, lib: VoiceLibrary
) -> None:
    """Deleting a voice while its preview renders must not recreate its folder (I9)."""
    vid = await client.post("/v1/voices/import", json={"style": make_style(), "name": "Brief"})
    voice_id = vid.json()["id"]
    real = engine.render

    async def render_then_delete(*a: object, **k: object) -> object:
        out = await real(*a, **k)  # type: ignore[arg-type]
        lib.delete(voice_id)
        return out

    engine.render = render_then_delete  # type: ignore[method-assign,assignment]
    r = await client.get(f"/v1/voices/{voice_id}/preview")
    assert r.status_code == 404 and r.json()["error"]["code"] == "voice_not_found"
    assert not (lib.custom_dir / voice_id).exists()


async def test_presets_listed_with_names(client: AsyncClient) -> None:
    data = (await client.get("/v1/voices?kind=preset")).json()["data"]
    f1 = next(v for v in data if v["id"] == "F1")
    assert f1["name"] == "Mia" and f1["description"].startswith("Higher-pitched female voice")
    custom = (
        await client.post("/v1/voices/import", json={"style": make_style(), "name": "Narrator"})
    ).json()
    assert set(f1) == set(custom)  # one shape for presets and custom voices


async def test_lookup_by_preset_name(client: AsyncClient) -> None:
    assert (await client.get("/v1/voices/mia")).json()["id"] == "F1"
    assert (await client.get("/v1/voices/HUGO/style")).status_code == 200
    r = await client.get("/v1/voices/Mia/preview")
    assert r.status_code == 200 and r.content[:4] == b"RIFF" and r.headers["x-voice-id"] == "F1"
    assert (await client.get("/v1/voices/F1/preview")).content == r.content  # one cache entry


async def test_custom_voice_cannot_take_a_preset_name(client: AsyncClient) -> None:
    r = await client.post("/v1/voices/import", json={"style": make_style(), "name": "mia"})
    err = r.json()["error"]
    assert r.status_code == 409 and err["code"] == "voice_name_taken" and err["param"] == "name"
    vid = (
        await client.post("/v1/voices/import", json={"style": make_style(), "name": "Narrator"})
    ).json()["id"]
    r = await client.patch(f"/v1/voices/{vid}", json={"name": "M1"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "voice_name_taken"
