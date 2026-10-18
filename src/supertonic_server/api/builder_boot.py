"""Choose and start the voice builder during app startup."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from supertonic_server.builder import Builder
from supertonic_server.builder.availability import detect_local_builder
from supertonic_server.builder.jobs import JobManager
from supertonic_server.builder.remote import RemoteBuilder
from supertonic_server.core.config import Settings
from supertonic_server.voices import VoiceLibrary

logger = logging.getLogger(__name__)


def detail_for(builder: Builder) -> dict[str, Any]:
    """Health detail for a builder whose hardware is unknown (only its methods)."""
    return {"device": None, "vram_mb": None, "methods": list(builder.methods)}


async def start_builder(
    settings: Settings, library: VoiceLibrary, model_dir: Path
) -> tuple[Builder | None, dict[str, Any] | None]:
    """Return the started builder and its health detail, or ``(None, None)`` when there is none.

    A failing probe or start never stops the server: it is logged and building is disabled.
    """
    try:
        return await _start(settings, library, model_dir)
    except Exception:
        logger.exception("voice builder failed to start; voice building is disabled")
        return None, None


async def _start(
    settings: Settings, library: VoiceLibrary, model_dir: Path
) -> tuple[Builder | None, dict[str, Any] | None]:
    if settings.builder == "off":
        return None, None
    if settings.builder_url:
        # Reachability is checked per build (503 builder_unavailable), not here.
        remote = RemoteBuilder(
            settings.builder_url, settings.builder_api_key, library, settings.data_dir
        )
        await remote.start()
        logger.info("forwarding voice builds to %s", remote.host)
        return remote, remote.detail()
    probe = await asyncio.to_thread(detect_local_builder)
    if not probe.available:
        if settings.builder == "local":
            logger.error("SUPERTONIC_BUILDER=local but no local builder: %s", probe.reason)
        else:
            logger.info("voice building unavailable on this machine: %s", probe.reason)
        return None, None
    manager = JobManager(
        settings.data_dir,
        library,
        model_dir,
        timeout_s=settings.builder_timeout_min * 60,
        methods=probe.methods,
    )
    await manager.start()
    detail = {"device": probe.device, "vram_mb": probe.vram_mb, "methods": list(probe.methods)}
    return manager, detail
