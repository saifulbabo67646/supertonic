"""Command-line entry point: ``supertonic-server serve`` and ``supertonic-server launch``."""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Sequence
from typing import Any

from pydantic import ValidationError

from supertonic_server import launch
from supertonic_server.core.config import ConfigError, Settings
from supertonic_server.core.logs import RedactApiKeyFilter


def _settings(overrides: dict[str, Any]) -> Settings:
    """Read the settings with command-line overrides; exits with status 2 when invalid."""
    try:
        return Settings(**overrides)
    except (ConfigError, ValidationError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc


def _serve(settings: Settings, watcher: launch.ReadyWatcher | None = None) -> bool:
    """Run the server until it stops; return whether it started.

    Exits with status 2 on unsafe configuration. ``watcher`` (if any) is started just before
    the server and stopped when it returns.
    """
    try:
        from supertonic_server.api import create_app

        app = create_app(settings)
    except (ConfigError, ValidationError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc

    import uvicorn

    auth = "API key required" if settings.api_key else "no API key required"
    print(f"Supertonic server: http://{settings.host}:{settings.port} ({auth})", flush=True)
    server = uvicorn.Server(uvicorn.Config(app, host=settings.host, port=settings.port))
    # uvicorn configures its loggers in Config(); add the filter afterwards so it sticks.
    # uvicorn.error also logs the WebSocket path (query string included) on accept.
    for name in ("uvicorn.access", "uvicorn.error"):
        logging.getLogger(name).addFilter(RedactApiKeyFilter())
    if watcher is not None:
        watcher.start()
    try:
        server.run()
    finally:
        if watcher is not None:
            watcher.stop()
    return bool(server.started)


def _launch(settings: Settings, *, open_browser: bool) -> int:
    """Open a running Studio, or pick a port, start the server and open the Studio."""
    if launch.already_running(settings.host, settings.port, open_browser=open_browser):
        return 0
    try:
        port = launch.choose_port(settings.host, settings.port)
    except launch.NoFreePortError as exc:
        launch.fail(f"{exc}. Close the program using them, or set SUPERTONIC_PORT.")
        return 1
    if port != settings.port:
        launch.say(f"Port {settings.port} is used by another program, so Supertonic uses {port}.")
        settings = settings.model_copy(update={"port": port})
    launch.first_start_note()
    watcher = launch.ReadyWatcher(launch.studio_url(settings.host, port), open_browser=open_browser)
    try:
        started = _serve(settings, watcher)
    except KeyboardInterrupt:  # Ctrl+C: uvicorn shuts down, then re-raises the signal
        started = True
    except SystemExit as exc:
        # uvicorn exits this way when startup fails (model load, port bind); so does
        # unsafe configuration (status 2).
        if exc.code in (0, None):
            started = True
        else:
            launch.fail("the server stopped while starting (the reason is in the messages above).")
            return exc.code if isinstance(exc.code, int) else 1
    if not started:
        launch.fail("the server stopped while starting (the reason is in the messages above).")
        return 1
    launch.say("Supertonic has stopped.")
    return 0


def main(argv: Sequence[str] | None = None) -> None:
    """Parse arguments and run the chosen command; exits with status 2 on unsafe configuration."""
    parser = argparse.ArgumentParser(prog="supertonic-server")
    sub = parser.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve", help="run the HTTP server")
    serve.add_argument("--host", help="bind address (default: SUPERTONIC_HOST or 127.0.0.1)")
    serve.add_argument("--port", type=int, help="port (default: SUPERTONIC_PORT or 8787)")
    serve.add_argument(
        "--open", action="store_true", help="open the Studio in the browser once it is ready"
    )
    start = sub.add_parser(
        "launch",
        help="start for desktop use: reuse a running server or pick a free port, open the Studio",
    )
    start.add_argument("--port", type=int, help="preferred port (default: SUPERTONIC_PORT or 8787)")
    start.add_argument("--no-open", action="store_true", help="do not open the browser")
    args = parser.parse_args(argv)

    if args.command == "launch":
        settings = _settings({"port": args.port} if args.port is not None else {})
        raise SystemExit(_launch(settings, open_browser=not args.no_open))

    overrides = {k: v for k, v in (("host", args.host), ("port", args.port)) if v is not None}
    settings = _settings(overrides)
    watcher = None
    if args.open:
        watcher = launch.ReadyWatcher(
            launch.studio_url(settings.host, settings.port), open_browser=True
        )
    _serve(settings, watcher)
