"""Tests for the smoke test behind ``supertonic-server check``."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import httpx
import pytest
from starlette.testclient import TestClient

from supertonic_server import cli, smoke
from supertonic_server.api import create_app

if TYPE_CHECKING:
    from supertonic_server.core.config import Settings
    from supertonic_server.engine import Engine
    from supertonic_server.voices import VoiceLibrary


def test_run_checks_passes_on_a_working_server(
    settings: Settings, engine: Engine, lib: VoiceLibrary, tmp_path: Path
) -> None:
    out = tmp_path / "out" / "smoke.mp3"
    with TestClient(create_app(settings, engine, lib), base_url="http://localhost") as client:
        report = smoke.run_checks(client, out)
    assert report.words == smoke.TIMESTAMP_WORDS
    assert report.duration_ms > 0 and report.voices == 2
    assert out.read_bytes()[:3] == b"ID3" or out.read_bytes()[0] == 0xFF
    assert report.speech_bytes == out.stat().st_size


def test_run_checks_reports_a_failing_endpoint(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/health":
            return httpx.Response(200, json={"status": "ok", "model": "supertonic-3"})
        return httpx.Response(503, json={"error": {"code": "server_busy"}})

    client = httpx.Client(transport=httpx.MockTransport(handler), base_url="http://x")
    with pytest.raises(smoke.CheckFailed, match="speech: HTTP 503"):
        smoke.run_checks(client, tmp_path / "s.mp3")


def test_run_checks_rejects_another_program(tmp_path: Path) -> None:
    client = httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"status": "ok"})),
        base_url="http://x",
    )
    with pytest.raises(smoke.CheckFailed, match="health check"):
        smoke.run_checks(client, tmp_path / "s.mp3")


def test_check_command_fails_cleanly_without_a_server(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    with pytest.raises(SystemExit) as exc:
        cli.main(["check", "--url", "http://127.0.0.1:9", "--out", str(tmp_path / "s.mp3")])
    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert "FAIL: could not reach the server" in out
