"""Tests for redacting API keys from access logs (M2)."""

from __future__ import annotations

import logging

import pytest

from supertonic_server.core.logs import RedactApiKeyFilter, redact_api_key


@pytest.mark.parametrize(
    ("raw", "clean"),
    [
        ("/v1/audio/speech/websocket?api_key=s3cr3t", "/v1/audio/speech/websocket?api_key=***"),
        ("/ws?voice=F1&api_key=abc&speed=1.2", "/ws?voice=F1&api_key=***&speed=1.2"),
        ("/ws?API_KEY=abc", "/ws?API_KEY=***"),
        ("/ws?api_key=a%20b c", "/ws?api_key=*** c"),
        ("/v1/health", "/v1/health"),
    ],
)
def test_redact_api_key(raw: str, clean: str) -> None:
    assert redact_api_key(raw) == clean


def test_filter_rewrites_uvicorn_access_record() -> None:
    record = logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        __file__,
        1,
        '%s - "%s %s HTTP/%s" %d',
        ("127.0.0.1:5000", "GET", "/v1/audio/speech/websocket?api_key=s3cr3t", "1.1", 101),
        None,
    )
    assert RedactApiKeyFilter().filter(record) is True
    assert "s3cr3t" not in record.getMessage() and "api_key=***" in record.getMessage()


def test_cli_installs_filter(monkeypatch: pytest.MonkeyPatch, tmp_path: object) -> None:
    import uvicorn

    from supertonic_server.cli import main

    monkeypatch.setenv("SUPERTONIC_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(uvicorn.Server, "run", lambda self, sockets=None: None)
    access = logging.getLogger("uvicorn.access")
    before = list(access.filters)
    try:
        main(["serve"])
        assert any(isinstance(f, RedactApiKeyFilter) for f in access.filters)
    finally:
        access.filters[:] = before
