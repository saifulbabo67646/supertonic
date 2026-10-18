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
    assert Settings(workers=0).effective_workers() == 4
    monkeypatch.setattr(os, "cpu_count", lambda: 4)
    assert Settings(workers=0).effective_workers() == 2
    monkeypatch.setattr(os, "cpu_count", lambda: 1)
    assert Settings(workers=0).effective_workers() == 1
    monkeypatch.setattr(os, "cpu_count", lambda: 10)
    assert Settings(workers=3).effective_workers() == 3


def test_env_prefix_and_voices_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SUPERTONIC_PORT", "9000")
    monkeypatch.setenv("SUPERTONIC_DATA_DIR", str(tmp_path))
    s = Settings()
    assert s.port == 9000
    assert s.custom_voices_dir == s.data_dir / "voices"


def test_realtime_steps_default() -> None:
    assert Settings().realtime_steps == 3


def test_intra_op_threads_default_and_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(os, "cpu_count", lambda: 10)
    assert Settings().effective_intra_op_threads() == 3
    assert Settings(workers=2).effective_intra_op_threads() == 5
    assert Settings(intra_op_threads=2).effective_intra_op_threads() == 2


def test_realtime_steps_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUPERTONIC_REALTIME_STEPS", "5")
    assert Settings().realtime_steps == 5


def test_data_dir_expands_home() -> None:
    assert Settings(data_dir="~/st-data").data_dir == Path.home() / "st-data"  # type: ignore[arg-type]


@pytest.mark.parametrize("raw", ["", "   ", "\t\n"])
def test_blank_api_key_is_none(raw: str) -> None:
    assert Settings(api_key=raw).api_key is None
    assert Settings(api_key=" k ").api_key == "k"


@pytest.mark.parametrize(
    "kw",
    [
        {"realtime_steps": 0},
        {"realtime_steps": 101},
        {"workers": -1},
        {"max_queue": 0},
        {"port": 0},
        {"port": 65536},
        {"intra_op_threads": 0},
    ],
)
def test_bounds(kw: dict[str, int]) -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        Settings(**kw)  # type: ignore[arg-type]


def test_dotenv_in_cwd_does_not_leak_into_tests(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Tests never read the developer's ./.env (D2)."""
    (tmp_path / ".env").write_text("SUPERTONIC_PORT=1234\nSUPERTONIC_API_KEY=leak\n")
    monkeypatch.chdir(tmp_path)
    s = Settings()
    assert (s.port, s.api_key) == (8787, None)


def test_builder_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    from pydantic import ValidationError

    s = Settings()
    assert (s.builder, s.builder_url, s.builder_api_key, s.builder_timeout_min) == (
        "auto",
        None,
        None,
        150,
    )
    monkeypatch.setenv("SUPERTONIC_BUILDER", "local")
    monkeypatch.setenv("SUPERTONIC_BUILDER_API_KEY", "  ")
    monkeypatch.setenv("SUPERTONIC_BUILDER_TIMEOUT_MIN", "5")
    s = Settings()
    assert (s.builder, s.builder_api_key, s.builder_timeout_min) == ("local", None, 5)
    with pytest.raises(ValidationError):
        Settings(builder="sometimes")  # type: ignore[arg-type]


def test_allowed_hosts_and_origins_are_comma_separated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUPERTONIC_ALLOWED_HOSTS", "tts.lan, studio.local ,")
    monkeypatch.setenv("SUPERTONIC_ALLOWED_ORIGINS", "http://localhost:3000")
    s = Settings()
    assert s.allowed_hosts == ["tts.lan", "studio.local"]
    assert s.allowed_origins == ["http://localhost:3000"]
    assert Settings(allowed_hosts=[]).allowed_hosts == []
