"""Tests for the static web UI served at ``/``."""

from __future__ import annotations

import httpx
import pytest


@pytest.mark.parametrize(
    ("path", "content_type", "marker"),
    [
        ("/", "text/html", '<script type="module" src="/js/app.js">'),
        ("/styles.css", "text/css", "--accent"),
        ("/js/app.js", "text/javascript", "hashchange"),
        ("/js/api.js", "text/javascript", "Bearer"),
    ],
)
async def test_web_assets_served(
    client: httpx.AsyncClient, path: str, content_type: str, marker: str
) -> None:
    r = await client.get(path)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith(content_type)
    assert marker in r.text


async def test_web_assets_public_when_key_set(authed_client: httpx.AsyncClient) -> None:
    r = await authed_client.get("/js/speak.js")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/javascript")
