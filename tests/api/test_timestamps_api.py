"""Tests for ``POST /v1/tts/timestamps``."""

from __future__ import annotations

import base64
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from httpx import AsyncClient


async def test_timestamps(client: AsyncClient) -> None:
    j = (
        await client.post("/v1/tts/timestamps", json={"text": "Hello world. Bye.", "voice": "F1"})
    ).json()
    assert j["timing_source"] == "estimated" and j["timing_unit"] == "word"
    assert j["sample_rate"] == 44100 and j["format"] == "wav" and j["language"] == "en"
    assert base64.b64decode(j["audio_base64"])[:4] == b"RIFF"
    assert [w["text"] for w in j["words"]] == ["Hello", "world.", "Bye."]
    assert j["segments"][1]["start_ms"] >= j["segments"][0]["end_ms"] + 290
    assert j["words"][-1]["end_ms"] <= j["duration_ms"]
    assert j["words"][1]["end_ms"] <= j["segments"][0]["end_ms"]
    assert j["words"][2]["start_ms"] >= j["segments"][1]["start_ms"]
    jj = (
        await client.post(
            "/v1/tts/timestamps", json={"text": "はい。", "voice": "F1", "language": "ja"}
        )
    ).json()
    assert jj["timing_unit"] == "character"


async def test_voice_by_preset_name(client: AsyncClient) -> None:
    r = await client.post("/v1/tts/timestamps", json={"text": "Hi.", "voice": "hugo"})
    assert r.status_code == 200 and r.json()["voice"] == "M1"


async def test_mp3_format(client: AsyncClient) -> None:
    j = (
        await client.post(
            "/v1/tts/timestamps", json={"text": "Hi.", "voice": "F1", "response_format": "mp3"}
        )
    ).json()
    assert j["format"] == "mp3" and base64.b64decode(j["audio_base64"])[:3] in (b"ID3", b"\xff\xfb")


async def test_errors(client: AsyncClient) -> None:
    async def post(**body: object) -> tuple[int, str]:
        r = await client.post("/v1/tts/timestamps", json={"text": "Hi.", "voice": "F1", **body})
        return r.status_code, r.json()["error"]["code"]

    # Validated by the schema (Literal), like /v1/audio/speech: invalid_request + param.
    r = await client.post(
        "/v1/tts/timestamps", json={"text": "Hi.", "voice": "F1", "response_format": "flac"}
    )
    assert r.status_code == 400 and r.json()["error"]["param"] == "response_format"
    assert r.json()["error"]["code"] == "invalid_request"
    assert await post(voice="nope") == (404, "voice_not_found")
    assert (await post(language="xx"))[0] == 400
    assert await post(speed=5) == (400, "invalid_speed")
    assert await post(text="😀") == (400, "empty_input")


async def test_long_text_capped(client: AsyncClient) -> None:
    r = await client.post("/v1/tts/timestamps", json={"text": "Hi. " * 5001, "voice": "F1"})
    assert r.status_code == 400 and r.json()["error"]["code"] == "input_too_long"
