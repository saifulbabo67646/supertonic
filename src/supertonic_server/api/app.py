"""FastAPI application factory."""

from __future__ import annotations

import mimetypes
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from importlib.resources import files
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from supertonic_server.api.deps import AppState
from supertonic_server.api.errors import install_error_handlers
from supertonic_server.api.guard import Guard
from supertonic_server.api.routes import ROUTERS
from supertonic_server.core.config import Settings, check_startup
from supertonic_server.engine import Engine, load_engine
from supertonic_server.voices import VoiceLibrary


def create_app(
    settings: Settings, engine: Engine | None = None, library: VoiceLibrary | None = None
) -> FastAPI:
    """Build the app. Raises ``ConfigError`` on unsafe configuration.

    When ``engine``/``library`` are omitted they are loaded during startup.
    """
    if (engine is None) != (library is None):
        raise ValueError("pass both engine and library, or neither")
    check_startup(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        loaded = False
        if engine is None or library is None:
            eng, presets = load_engine(settings)
            lib = VoiceLibrary(presets, settings.custom_voices_dir)
            app.state.app_state = AppState(settings, eng, lib)
            loaded = True
        try:
            yield
        finally:
            if loaded:
                app.state.app_state.engine.scheduler.close()

    app = FastAPI(title="Supertonic Server", lifespan=lifespan)
    if engine is not None and library is not None:
        app.state.app_state = AppState(settings, engine, library)
    install_error_handlers(app)
    # Auth, the forwarded-header check and the body cap run before routing and parsing.
    app.add_middleware(Guard, api_key=settings.api_key)
    for router in ROUTERS:
        app.include_router(router)
    # ES modules need a JavaScript MIME type; some Windows registries map .js to text/plain.
    mimetypes.add_type("text/javascript", ".js")
    web = Path(str(files("supertonic_server") / "web"))
    app.mount("/", StaticFiles(directory=web, html=True), name="web")
    return app
