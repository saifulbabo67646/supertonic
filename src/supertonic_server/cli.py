"""Command-line entry point: ``supertonic-server serve``."""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Sequence

from pydantic import ValidationError

from supertonic_server.core.config import ConfigError, Settings
from supertonic_server.core.logs import RedactApiKeyFilter


def main(argv: Sequence[str] | None = None) -> None:
    """Parse arguments and run the server; exits with status 2 on unsafe configuration."""
    parser = argparse.ArgumentParser(prog="supertonic-server")
    sub = parser.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve", help="run the HTTP server")
    serve.add_argument("--host", help="bind address (default: SUPERTONIC_HOST or 127.0.0.1)")
    serve.add_argument("--port", type=int, help="port (default: SUPERTONIC_PORT or 8787)")
    args = parser.parse_args(argv)

    overrides = {k: v for k, v in (("host", args.host), ("port", args.port)) if v is not None}
    try:
        settings = Settings(**overrides)
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
    server.run()
