"""FastAPI application factory."""

from __future__ import annotations

import mimetypes
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from importlib.resources import files
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.responses import Response

from supertonic_server.api.builder_boot import start_builder
from supertonic_server.api.deps import AppState
from supertonic_server.api.errors import install_error_handlers
from supertonic_server.api.guard import Guard
from supertonic_server.api.routes import ROUTERS
from supertonic_server.builder import Builder
from supertonic_server.core.config import Settings, check_startup
from supertonic_server.engine import Engine, load_engine
from supertonic_server.voices import VoiceLibrary


class StudioFiles(StaticFiles):
    """Static files that browsers revalidate on every load (``Cache-Control: no-cache``).

    The Studio is a set of ES modules; without this, a browser may keep some old modules after
    an upgrade and mix them with new ones, which leaves a blank page.
    """

    def file_response(self, *args: Any, **kwargs: Any) -> Response:
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "no-cache"
        return response


def create_app(
    settings: Settings,
    engine: Engine | None = None,
    library: VoiceLibrary | None = None,
    builder: Builder | None = None,
) -> FastAPI:
    """Build the app. Raises ``ConfigError`` on unsafe configuration.

    When ``engine``/``library`` are omitted they are loaded during startup, and the voice
    builder is chosen from the settings. An injected ``builder`` (tests) is used as is: it is
    neither probed nor started or closed here.
    """
    if (engine is None) != (library is None):
        raise ValueError("pass both engine and library, or neither")
    if builder is not None and engine is None:
        raise ValueError("an injected builder needs an injected engine and library")
    check_startup(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        loaded = False
        if engine is None or library is None:
            eng, presets = load_engine(settings)
            lib = VoiceLibrary(presets, settings.custom_voices_dir)
            state = AppState(settings, eng, lib)
            app.state.app_state = state
            loaded = True
        try:
            if loaded:
                state = app.state.app_state
                state.builder = await start_builder(settings, state.library, presets.parent)
            yield
        finally:
            if loaded:
                started = app.state.app_state.builder
                try:
                    if started is not None:
                        await started.close()
                finally:
                    app.state.app_state.engine.scheduler.close()

    app = FastAPI(title="Supertonic Server", lifespan=lifespan)
    if engine is not None and library is not None:
        app.state.app_state = AppState(settings, engine, library, builder)
    install_error_handlers(app)
    # Auth, the forwarded-header, Host and Origin checks and the body cap run before routing
    # and parsing.
    app.add_middleware(
        Guard,
        api_key=settings.api_key,
        bind_host=settings.host,
        allowed_hosts=settings.allowed_hosts,
        allowed_origins=settings.allowed_origins,
    )
    for router in ROUTERS:
        app.include_router(router)
    # ES modules need a JavaScript MIME type; some Windows registries map .js to text/plain.
    mimetypes.add_type("text/javascript", ".js")
    web = Path(str(files("supertonic_server") / "web"))
    app.mount("/", StudioFiles(directory=web, html=True), name="web")
    return app
