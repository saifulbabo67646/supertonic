"""Server settings (environment / ``.env``) and the startup safety check."""

from __future__ import annotations

import math
import os
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


class ConfigError(Exception):
    """Raised when the configuration is unsafe or invalid; the server must not start."""


class Settings(BaseSettings):
    """Runtime configuration, read from ``SUPERTONIC_*`` environment variables or ``.env``."""

    model_config = SettingsConfigDict(env_prefix="SUPERTONIC_", env_file=".env", extra="ignore")

    host: str = "127.0.0.1"
    port: int = 8787
    api_key: str | None = None
    public_url: str | None = None
    data_dir: Path = Path.home() / ".supertonic-server"
    model_dir: Path | None = None
    workers: int = 0
    intra_op_threads: int | None = None
    max_queue: int = 64
    realtime_steps: int = 3
    default_voice: str = "F1"
    builder_url: str | None = None

    def effective_workers(self) -> int:
        """Return the worker count; ``workers == 0`` means ``min(4, max(1, cpu_count // 2))``."""
        if self.workers > 0:
            return self.workers
        return min(4, max(1, (os.cpu_count() or 1) // 2))

    def effective_intra_op_threads(self) -> int:
        """Return threads per worker; unset means ``ceil(cpu_count / effective_workers())``."""
        if self.intra_op_threads is not None and self.intra_op_threads > 0:
            return self.intra_op_threads
        return math.ceil((os.cpu_count() or 1) / self.effective_workers())

    @property
    def custom_voices_dir(self) -> Path:
        """Directory holding user-created voice styles."""
        return self.data_dir / "voices"


def check_startup(settings: Settings) -> None:
    """Refuse to start when the server is reachable from other machines without an API key."""
    exposed = settings.host not in LOOPBACK_HOSTS or bool(settings.public_url)
    if exposed and not settings.api_key:
        raise ConfigError(
            "SUPERTONIC_API_KEY must be set when the server is reachable from other machines "
            f"(host={settings.host}, public_url={settings.public_url})"
        )
