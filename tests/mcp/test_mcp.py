"""Tests for the stdio MCP server, driven in-process against the fake-engine app."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from supertonic_server.mcp.client import SupertonicApiError, SupertonicClient
from supertonic_server.mcp.server import build_server


@pytest.fixture
async def mcp(client: httpx.AsyncClient, tmp_path: Path) -> AsyncIterator[MCPServer]:
    """MCP server wired to the fake-engine app; files land in ``tmp_path/out``."""
    yield build_server(SupertonicClient(client), tmp_path / "out")


def head(path: str, n: int = 4) -> bytes:
    """First ``n`` bytes of a file."""
    return Path(path).read_bytes()[:n]


def size(path: str) -> int:
    """Size of a file in bytes."""
    return Path(path).stat().st_size


async def call(server: MCPServer, name: str, **args: Any) -> Any:
    """Call a tool in-process and return its structured result."""
    result = await server.call_tool(name, args)
    assert not result.is_error
    data = result.structured_content
    assert data is not None
    return data.get("result", data)


async def test_list_voices_and_languages(mcp: MCPServer) -> None:
    assert {"code": "ja", "name": "Japanese"} in await call(mcp, "list_languages")
    voices = await call(mcp, "list_voices")
    assert "F1" in [v["id"] for v in voices]
    assert set(voices[0]) == {"id", "name", "kind", "gender", "tags", "description"}


async def test_list_voices_filters(mcp: MCPServer) -> None:
    assert await call(mcp, "list_voices", kind="custom") == []
    assert await call(mcp, "list_voices", tag="nope") == []


async def test_speak_writes_file(mcp: MCPServer, tmp_path: Path) -> None:
    out = await call(mcp, "speak", text="Hello.", voice="F1", format="wav")
    p = Path(out["path"])
    assert p.parent == tmp_path / "out" and head(out["path"]) == b"RIFF"
    assert p.name.startswith("F1-") and p.suffix == ".wav"
    assert out["voice"] == "F1" and out["language"] == "en"
    assert out["duration_ms"] > 0


async def test_speak_wav_is_a_valid_file(mcp: MCPServer) -> None:
    """The streamed WAV's unknown-length header is fixed before saving (I8)."""
    import wave

    out = await call(mcp, "speak", text="Hello there. Bye.", voice="F1", format="wav")
    with wave.open(out["path"]) as w:
        frames, rate = w.getnframes(), w.getframerate()
    total = size(out["path"])
    assert rate == 44100 and frames == (total - 44) // 2
    assert int.from_bytes(head(out["path"], 8)[4:], "little") == total - 8
    assert out["duration_ms"] == round(frames / rate * 1000)


async def test_speak_pcm_duration_and_ext(mcp: MCPServer) -> None:
    out = await call(mcp, "speak", text="Hello.", voice="F1", format="pcm")
    p = Path(out["path"])
    assert p.suffix == ".pcm"
    assert out["duration_ms"] == round(size(out["path"]) / 2 / 24000 * 1000)


async def test_speak_compressed_duration_null(mcp: MCPServer) -> None:
    out = await call(mcp, "speak", text="Hello.", voice="F1", format="mp3")
    assert out["duration_ms"] is None and size(out["path"]) > 0


async def test_speak_with_timestamps(mcp: MCPServer) -> None:
    out = await call(mcp, "speak", text="Hello world.", voice="M1", timestamps=True)
    assert [w["text"] for w in out["words"]] == ["Hello", "world."]
    assert out["duration_ms"] > 0 and head(out["path"]) == b"RIFF"


async def test_timestamps_rejects_other_formats(mcp: MCPServer) -> None:
    with pytest.raises(ToolError, match="wav or mp3"):
        await call(mcp, "speak", text="Hi.", voice="F1", format="flac", timestamps=True)


async def test_speak_output_path(mcp: MCPServer, tmp_path: Path) -> None:
    target = tmp_path / "a" / "b" / "x.wav"
    out = await call(mcp, "speak", text="Hi.", voice="F1", output_path=str(target))
    assert out["path"] == str(target) and target.exists()
    target.write_bytes(b"old")
    await call(mcp, "speak", text="Hi.", voice="F1", output_path=str(target))
    assert target.read_bytes()[:4] == b"RIFF"


async def test_speak_output_path_expands_home(
    mcp: MCPServer, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    out = await call(mcp, "speak", text="Hi.", voice="F1", output_path="~/h.wav")
    assert out["path"] == str(tmp_path / "h.wav")


async def test_default_names_never_collide(mcp: MCPServer) -> None:
    a = await call(mcp, "speak", text="Hi.", voice="F1")
    b = await call(mcp, "speak", text="Hi.", voice="F1")
    assert a["path"] != b["path"]


async def test_preview_voice(mcp: MCPServer) -> None:
    out = await call(mcp, "preview_voice", voice="F1", language="en")
    assert head(out["path"]) == b"RIFF"


async def test_error_surfaces_code(mcp: MCPServer) -> None:
    with pytest.raises(ToolError, match=r"voice_not_found\)"):
        await call(mcp, "speak", text="Hi.", voice="nobody")
    with pytest.raises(ToolError, match="invalid_speed"):
        await call(mcp, "speak", text="Hi.", voice="F1", speed=5.0)


async def test_error_does_not_write_file(mcp: MCPServer, tmp_path: Path) -> None:
    with pytest.raises(ToolError):
        await call(mcp, "speak", text="Hi.", voice="nobody")
    assert not list((tmp_path / "out").glob("*"))


async def test_client_sends_api_key(
    client: httpx.AsyncClient, authed_client: httpx.AsyncClient
) -> None:
    with pytest.raises(SupertonicApiError) as exc:
        await SupertonicClient(authed_client).languages()
    assert exc.value.status == 401
    keyed = SupertonicClient(authed_client, api_key="secret")
    assert await keyed.languages()


async def test_client_error_fallback_for_non_json(client: httpx.AsyncClient) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(502, text="bad gateway")

    c = SupertonicClient(
        httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://x")
    )
    with pytest.raises(SupertonicApiError) as exc:
        await c.languages()
    assert exc.value.status == 502 and exc.value.code == "http_error"
