"""The desktop launch helpers: port choice, already-running detection, browser opening."""

from __future__ import annotations

import socket
from typing import Any

import pytest

from supertonic_server import cli, launch
from supertonic_server.core.config import Settings

HEALTH = {"status": "ok", "model": "supertonic-3"}


def test_studio_url_uses_loopback_for_wildcard_hosts() -> None:
    assert launch.studio_url("127.0.0.1", 8787) == "http://127.0.0.1:8787/"
    assert launch.studio_url("0.0.0.0", 8788) == "http://127.0.0.1:8788/"
    assert launch.studio_url("::", 8788) == "http://127.0.0.1:8788/"
    assert launch.studio_url("::1", 8787) == "http://[::1]:8787/"


def test_is_supertonic_needs_the_model_id() -> None:
    assert launch.is_supertonic(HEALTH)
    assert not launch.is_supertonic({"status": "ok"})
    assert not launch.is_supertonic(None)


def test_choose_port_prefers_the_requested_port() -> None:
    assert launch.choose_port("127.0.0.1", 8787, is_free=lambda h, p: True) == 8787


def test_choose_port_skips_busy_ports() -> None:
    busy = {8787, 8788}
    port = launch.choose_port("127.0.0.1", 8787, is_free=lambda h, p: p not in busy)
    assert port == 8789


def test_choose_port_gives_up_after_the_span() -> None:
    tried: list[int] = []

    def never(host: str, port: int) -> bool:
        tried.append(port)
        return False

    with pytest.raises(launch.NoFreePortError, match="8787 to 8799"):
        launch.choose_port("127.0.0.1", 8787, is_free=never)
    assert tried == list(range(8787, 8800))


def test_port_is_free_sees_a_listening_socket() -> None:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen()
        port = sock.getsockname()[1]
        assert not launch.port_is_free("127.0.0.1", port)
    assert launch.port_is_free("127.0.0.1", port)


def test_probe_health_returns_none_when_nothing_listens() -> None:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    assert launch.probe_health(f"http://127.0.0.1:{port}/", timeout=0.5) is None


def test_already_running_opens_the_browser() -> None:
    opened: list[str] = []
    found = launch.already_running(
        "127.0.0.1",
        8787,
        open_browser=True,
        probe=lambda url: HEALTH,
        opener=lambda url: opened.append(url) or True,
    )
    assert found
    assert opened == ["http://127.0.0.1:8787/"]


def test_already_running_with_no_open_leaves_the_browser_alone() -> None:
    opened: list[str] = []
    found = launch.already_running(
        "127.0.0.1",
        8787,
        open_browser=False,
        probe=lambda url: HEALTH,
        opener=lambda url: opened.append(url) or True,
    )
    assert found
    assert opened == []


def test_another_program_on_the_port_is_not_supertonic() -> None:
    found = launch.already_running(
        "127.0.0.1",
        8787,
        open_browser=True,
        probe=lambda url: {"status": "ok"},
        opener=lambda url: pytest.fail("must not open"),
    )
    assert not found


def test_open_in_browser_falls_back_to_printing_the_url(capsys: pytest.CaptureFixture[str]) -> None:
    launch.open_in_browser("http://127.0.0.1:8787/", lambda url: False)
    assert "Open this address yourself: http://127.0.0.1:8787/" in capsys.readouterr().out

    def broken(url: str) -> bool:
        raise RuntimeError("no browser")

    launch.open_in_browser("http://127.0.0.1:8787/", broken)
    assert "Open this address yourself" in capsys.readouterr().out


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


def test_watcher_opens_the_browser_once_healthy(capsys: pytest.CaptureFixture[str]) -> None:
    answers: list[dict[str, Any] | None] = [None] * 10 + [HEALTH]
    opened: list[str] = []
    clock = FakeClock()
    watcher = launch.ReadyWatcher(
        "http://127.0.0.1:8790/",
        open_browser=True,
        interval=1.0,
        dot_every=3.0,
        probe=lambda url: answers.pop(0),
        opener=lambda url: opened.append(url) or True,
        clock=clock,
        sleep=clock.sleep,
    )
    watcher.run()
    assert watcher.ready
    assert opened == ["http://127.0.0.1:8790/"]
    out = capsys.readouterr().out
    assert out.count(".") >= 3
    assert "Supertonic is ready: http://127.0.0.1:8790/" in out


def test_watcher_without_open_only_announces() -> None:
    watcher = launch.ReadyWatcher(
        "http://127.0.0.1:8790/",
        open_browser=False,
        probe=lambda url: HEALTH,
        opener=lambda url: pytest.fail("must not open"),
    )
    watcher.run()
    assert watcher.ready


def test_watcher_gives_up_after_the_timeout(capsys: pytest.CaptureFixture[str]) -> None:
    clock = FakeClock()
    watcher = launch.ReadyWatcher(
        "http://127.0.0.1:8790/",
        open_browser=True,
        timeout=10.0,
        interval=1.0,
        probe=lambda url: None,
        opener=lambda url: pytest.fail("must not open"),
        clock=clock,
        sleep=clock.sleep,
    )
    watcher.run()
    assert not watcher.ready
    assert "taking much longer than usual" in capsys.readouterr().out


def test_watcher_stops_when_asked() -> None:
    watcher = launch.ReadyWatcher(
        "http://127.0.0.1:8790/",
        open_browser=True,
        probe=lambda url: pytest.fail("must not probe"),
    )
    watcher.stop()
    watcher.run()
    assert not watcher.ready


def test_launch_reuses_a_running_server(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(launch, "probe_health", lambda url, timeout=1.0: HEALTH)
    monkeypatch.setattr(cli, "_serve", lambda *a, **k: pytest.fail("must not start a server"))
    opened: list[str] = []
    monkeypatch.setattr(launch.webbrowser, "open", lambda url: opened.append(url) or True)
    assert cli._launch(Settings(_env_file=None), open_browser=True) == 0  # type: ignore[call-arg]
    assert opened == ["http://127.0.0.1:8787/"]


def test_launch_moves_to_a_free_port(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    served: list[tuple[int, str, bool]] = []

    def fake_serve(settings: Settings, watcher: launch.ReadyWatcher | None = None) -> bool:
        assert watcher is not None
        served.append((settings.port, watcher.url, watcher.open_browser))
        return True

    monkeypatch.setattr(launch, "already_running", lambda host, port, *, open_browser: False)
    monkeypatch.setattr(cli, "_serve", fake_serve)
    real_choose = launch.choose_port
    monkeypatch.setattr(
        launch,
        "choose_port",
        lambda host, port: real_choose(host, port, is_free=lambda h, p: p != 8787),
    )
    assert cli._launch(Settings(_env_file=None), open_browser=False) == 0  # type: ignore[call-arg]
    assert served == [(8788, "http://127.0.0.1:8788/", False)]
    assert "Port 8787 is used by another program, so Supertonic uses 8788." in (
        capsys.readouterr().out
    )


def test_launch_reports_a_failed_start(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(launch, "already_running", lambda host, port, *, open_browser: False)
    monkeypatch.setattr(launch, "choose_port", lambda host, port: port)
    monkeypatch.setattr(cli, "_serve", lambda settings, watcher=None: False)
    assert cli._launch(Settings(_env_file=None), open_browser=False) == 1  # type: ignore[call-arg]
    assert "docs/troubleshooting.md" in capsys.readouterr().out


def test_launch_when_every_port_is_busy(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def no_port(host: str, port: int) -> int:
        raise launch.NoFreePortError("ports 8787 to 8799 are all in use")

    monkeypatch.setattr(launch, "already_running", lambda host, port, *, open_browser: False)
    monkeypatch.setattr(launch, "choose_port", no_port)
    assert cli._launch(Settings(_env_file=None), open_browser=False) == 1  # type: ignore[call-arg]
    assert "all in use" in capsys.readouterr().out


def test_serve_open_starts_a_watcher(monkeypatch: pytest.MonkeyPatch, tmp_path: object) -> None:
    seen: list[launch.ReadyWatcher | None] = []
    monkeypatch.setenv("SUPERTONIC_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(cli, "_serve", lambda settings, watcher=None: seen.append(watcher) or True)
    cli.main(["serve", "--port", "8791", "--open"])
    cli.main(["serve", "--port", "8791"])
    assert seen[0] is not None and seen[0].open_browser
    assert seen[0].url == "http://127.0.0.1:8791/"
    assert seen[1] is None


def test_launch_command_passes_no_open(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[int, bool]] = []
    monkeypatch.setattr(
        cli,
        "_launch",
        lambda settings, *, open_browser: calls.append((settings.port, open_browser)) or 0,
    )
    with pytest.raises(SystemExit) as exc:
        cli.main(["launch", "--port", "8792", "--no-open"])
    assert exc.value.code == 0
    assert calls == [(8792, False)]
