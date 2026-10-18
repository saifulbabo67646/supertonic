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
        ("/js/new-voice.js", "text/javascript", "Where is this recording from?"),
        ("/js/build-job.js", "text/javascript", "Stop and keep the best result so far"),
        ("/js/build-copy.js", "text/javascript", "Best match — about 1½ hours"),
        ("/js/voice-clips.js", "text/javascript", "dataTransfer"),
        ("/js/build-result.js", "text/javascript", "Open voice card"),
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
    assert "Quick draft — about 10 minutes" in copy
    assert "OpenRAIL-M" in copy
    assert "Finishing: matching the speaking pace…" in copy
    job_view = (await client.get("/js/build-job.js")).text
    assert "FINISHING_LABELS[p?.stage]" in job_view
    screen = (await client.get("/js/new-voice.js")).text
    assert "I have the speaker's permission to create and use this voice" in screen


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
