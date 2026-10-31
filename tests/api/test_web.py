"""Tests for the static web UI served at ``/``."""

from __future__ import annotations

import re
from importlib.resources import files
from pathlib import Path

import httpx
import pytest

WEB = Path(str(files("supertonic_server") / "web"))


@pytest.mark.parametrize(
    ("path", "content_type", "marker"),
    [
        ("/", "text/html", '<script type="module" src="/js/app.js">'),
        ("/styles.css", "text/css", "--accent"),
        ("/js/app.js", "text/javascript", "hashchange"),
        ("/js/api.js", "text/javascript", "Bearer"),
        ("/js/new-voice-form.js", "text/javascript", "Where is this recording from?"),
        ("/js/build-job.js", "text/javascript", "Stop and keep the best result so far"),
        ("/js/build-copy.js", "text/javascript", "Best match — about 1½ hours"),
        ("/js/voice-clips.js", "text/javascript", "dataTransfer"),
        ("/js/build-result.js", "text/javascript", "See it in Voices"),
        ("/js/welcome.js", "text/javascript", "Welcome to Supertonic"),
        ("/js/voice-tips.js", "text/javascript", "Tips for a good recording"),
        ("/js/errors.js", "text/javascript", "docs/getting-started.md"),
        ("/js/voice-record.js", "text/javascript", "MediaRecorder"),
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


async def test_web_new_voice_view_present(client: httpx.AsyncClient) -> None:
    r = await client.get("/")
    assert 'id="view-new-voice"' in r.text
    app = (await client.get("/js/app.js")).text
    assert '"voices/new": "new-voice"' in app


async def test_web_new_voice_copy(client: httpx.AsyncClient) -> None:
    copy = (await client.get("/js/build-copy.js")).text
    assert "Quick draft — about 15 minutes" in copy
    assert "OpenRAIL-M" in copy
    assert "Finishing: matching the speaking pace…" in copy
    job_view = (await client.get("/js/build-job.js")).text
    assert "FINISHING_LABELS[p?.stage]" in job_view
    form = (await client.get("/js/new-voice-form.js")).text
    assert "I have the speaker's permission to create and use this voice" in form
    assert "noBuilderCard" in (await client.get("/js/new-voice.js")).text
    assert "NVIDIA graphics card" in copy
    assert "docs/builder.md" in (await client.get("/js/errors.js")).text


async def test_web_header_links_to_beginner_guide(client: httpx.AsyncClient) -> None:
    page = (await client.get("/")).text
    assert 'class="help-link"' in page
    assert "/blob/main/docs/getting-started.md" in page


async def test_web_relative_imports_are_served(client: httpx.AsyncClient) -> None:
    """Every ``from "./x.js"`` import names a module the server serves."""
    for module in sorted((WEB / "js").glob("*.js")):
        for name in re.findall(r'from "\./([\w-]+\.js)"', module.read_text(encoding="utf-8")):
            r = await client.get(f"/js/{name}")
            assert r.status_code == 200, f"{module.name} imports missing {name}"


def test_web_never_parses_html_or_opens_window_dialogs() -> None:
    banned = re.compile(r"innerHTML|outerHTML|insertAdjacentHTML|\b(alert|confirm|prompt)\(")
    for module in sorted((WEB / "js").glob("*.js")):
        text = module.read_text(encoding="utf-8")
        assert not banned.search(text), f"{module.name}: {banned.search(text)}"


async def test_web_stylesheets_are_served(client: httpx.AsyncClient) -> None:
    """Every stylesheet the page links is served as CSS, and every CSS file is linked."""
    page = (await client.get("/")).text
    linked = re.findall(r'<link rel="stylesheet" href="/([\w/.-]+\.css)"', page)
    assert linked[0] == "styles.css"
    for path in linked:
        r = await client.get(f"/{path}")
        assert r.status_code == 200, path
        assert r.headers["content-type"].startswith("text/css")
    on_disk = {"styles.css"} | {f"css/{p.name}" for p in (WEB / "css").glob("*.css")}
    assert set(linked) == on_disk


@pytest.mark.parametrize("path", ["/", "/js/app.js", "/styles.css"])
async def test_web_assets_revalidate(client: httpx.AsyncClient, path: str) -> None:
    """Browsers must not keep stale modules after an upgrade."""
    r = await client.get(path)
    assert r.headers["cache-control"] == "no-cache"
    etag = r.headers["etag"]
    again = await client.get(path, headers={"If-None-Match": etag})
    assert again.status_code == 304
