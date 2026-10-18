"""Tests for settings and the startup safety check."""

import os
from pathlib import Path

import pytest

from supertonic_server.core.config import ConfigError, Settings, check_startup


def test_loopback_without_key_ok() -> None:
    check_startup(Settings(host="127.0.0.1", api_key=None))


@pytest.mark.parametrize(
    "kw",
    [{"host": "0.0.0.0"}, {"host": "192.168.1.5"}, {"public_url": "https://tts.example.com"}],
)
def test_exposed_without_key_refuses(kw: dict[str, str]) -> None:
    with pytest.raises(ConfigError, match="SUPERTONIC_API_KEY"):
        check_startup(Settings(api_key=None, **kw))  # type: ignore[arg-type]


def test_exposed_with_key_ok() -> None:
    check_startup(Settings(host="0.0.0.0", api_key="k"))


def test_workers_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(os, "cpu_count", lambda: 10)
    assert Settings(workers=0).effective_workers() == 5
    assert Settings(workers=3).effective_workers() == 3


def test_env_prefix_and_voices_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SUPERTONIC_PORT", "9000")
    monkeypatch.setenv("SUPERTONIC_DATA_DIR", str(tmp_path))
    s = Settings()
    assert s.port == 9000
    assert s.custom_voices_dir == s.data_dir / "voices"
