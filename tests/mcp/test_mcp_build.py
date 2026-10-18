"""MCP build tools, driven in-process against the fake-worker JobManager."""

from __future__ import annotations

import asyncio
import sys
import time
from collections.abc import AsyncIterator, Callable, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx
import pytest
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from fakes_builder import FAKE_WORKER
from supertonic_server.api import create_app
from supertonic_server.builder import PreparedAudio, jobs
from supertonic_server.builder.jobs import JobManager
from supertonic_server.mcp.client import SupertonicClient
from supertonic_server.mcp.server import build_server

if TYPE_CHECKING:
    from fastapi import FastAPI

    from supertonic_server.core.config import Settings
    from supertonic_server.engine import Engine
    from supertonic_server.voices import VoiceLibrary

AppClient = Callable[["FastAPI"], httpx.AsyncClient]
TERMINAL = {"succeeded", "failed", "cancelled"}


def _fake_prepare(files: Sequence[tuple[str, bytes]], out_path: Path) -> PreparedAudio:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(b"RIFF-fake")
    return PreparedAudio(out_path, 5.0, 4.0, [n for n, _ in files])


@pytest.fixture
async def mcp(
    tmp_path: Path,
    settings: Settings,
    engine: Engine,
    lib: VoiceLibrary,
    app_client: AppClient,
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[MCPServer]:
    control = tmp_path / "control"
    control.mkdir()
    monkeypatch.setenv("FAKE_BUILDER_DIR", str(control))
    monkeypatch.setattr(jobs, "prepare_reference", _fake_prepare)
    mgr = JobManager(
        tmp_path / "data",
        lib,
        tmp_path / "models",
        timeout_s=30.0,
        worker_cmd=[sys.executable, FAKE_WORKER],
    )
    await mgr.start()
    async with app_client(create_app(settings, engine, lib, mgr)) as http:
        yield build_server(SupertonicClient(http), tmp_path / "out")
    await mgr.close()


@pytest.fixture
def audio(tmp_path: Path) -> str:
    path = tmp_path / "ref.wav"
    path.write_bytes(b"fake-audio")
    return str(path)


async def call(server: MCPServer, tool: str, /, **args: Any) -> Any:
    result = await server.call_tool(tool, args)
    assert not result.is_error
    data = result.structured_content
    assert data is not None
    return data.get("result", data)


async def wait_done(server: MCPServer, job_id: str, within: float = 10.0) -> dict[str, Any]:
    deadline = time.monotonic() + within
    while True:
        job: dict[str, Any] = await call(server, "get_job", job_id=job_id)
        if job["state"] in TERMINAL:
            return job
        assert time.monotonic() < deadline, f"job still {job['state']}"
        await asyncio.sleep(0.02)


def build_args(audio: str, **extra: Any) -> dict[str, Any]:
    return {
        "audio_paths": [audio],
        "name": "Narrator",
        "source_note": "my own voice",
        "consent": True,
        **extra,
    }


async def test_build_then_poll_get_job(mcp: MCPServer, audio: str) -> None:
    started = await call(mcp, "build_voice", **build_args(audio, tags=["a", "b"]))
    assert set(started) == {"job_id", "state", "method"} and started["method"] == "accurate"
    done = await wait_done(mcp, started["job_id"])
    assert done["state"] == "succeeded" and done["voice_id"]
    assert set(done) == {"state", "progress", "voice_id", "error"}
    voices = await call(mcp, "list_voices", kind="custom")
    assert done["voice_id"] in [v["id"] for v in voices]


async def test_fast_method_reaches_job(mcp: MCPServer, audio: str) -> None:
    started = await call(mcp, "build_voice", **build_args(audio, method="fast"))
    assert started["method"] == "fast"
    jobs_list = await call(mcp, "list_jobs", limit=5)
    assert jobs_list[0]["request"]["method"] == "fast"
    await wait_done(mcp, started["job_id"])


async def test_finish_job_succeeds(
    mcp: MCPServer, audio: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_BUILDER_MODES", "gate")
    job_id = (await call(mcp, "build_voice", **build_args(audio)))["job_id"]
    deadline = time.monotonic() + 10
    while (await call(mcp, "get_job", job_id=job_id))["state"] != "running":
        assert time.monotonic() < deadline, "job never started"
        await asyncio.sleep(0.02)  # noqa: ASYNC110 - polling a remote job state
    finished = await call(mcp, "finish_job", job_id=job_id)
    assert finished["state"] in {"running", "succeeded"}
    assert (await wait_done(mcp, job_id))["state"] == "succeeded"


async def test_consent_false_is_rejected_by_server(mcp: MCPServer, audio: str) -> None:
    with pytest.raises(ToolError, match="consent_required"):
        await mcp.call_tool("build_voice", build_args(audio, consent=False))


async def test_missing_file_names_path(mcp: MCPServer, tmp_path: Path) -> None:
    missing = str(tmp_path / "nope.wav")
    with pytest.raises(ToolError, match="nope.wav"):
        await mcp.call_tool("build_voice", build_args(missing))


async def test_unknown_job_is_tool_error(mcp: MCPServer) -> None:
    with pytest.raises(ToolError, match="job_not_found"):
        await mcp.call_tool("get_job", {"job_id": "nope"})
