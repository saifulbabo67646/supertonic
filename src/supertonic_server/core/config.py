"""Server settings (environment / ``.env``) and the startup safety check."""

from __future__ import annotations

import math
import os
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


class ConfigError(Exception):
    """Raised when the configuration is unsafe or invalid; the server must not start."""


class Settings(BaseSettings):
    """Runtime configuration, read from ``SUPERTONIC_*`` environment variables or ``.env``."""

    model_config = SettingsConfigDict(env_prefix="SUPERTONIC_", env_file=".env", extra="ignore")

    host: str = "127.0.0.1"
    port: int = Field(8787, ge=1, le=65535)
    api_key: str | None = None
    public_url: str | None = None
    # Without an API key: extra Host names and browser origins to accept (comma-separated).
    allowed_hosts: Annotated[list[str], NoDecode] = Field(default_factory=list)
    allowed_origins: Annotated[list[str], NoDecode] = Field(default_factory=list)
    data_dir: Path = Path.home() / ".supertonic-server"
    model_dir: Path | None = None
    workers: int = Field(0, ge=0)
    intra_op_threads: int | None = Field(None, ge=1)
    max_queue: int = Field(64, ge=1)
    realtime_steps: int = Field(3, ge=1, le=100)
    default_voice: str = "F1"
    builder: Literal["auto", "local", "off"] = "auto"
    builder_url: str | None = None
    builder_api_key: str | None = None
    builder_timeout_min: int = Field(150, ge=1)

    @field_validator("api_key", "builder_api_key", mode="before")
    @classmethod
    def _blank_key_is_none(cls, value: Any) -> Any:
        """Strip the key; an empty or whitespace-only key means "no key"."""
        if isinstance(value, str):
            return value.strip() or None
        return value

    @field_validator("allowed_hosts", "allowed_origins", mode="before")
    @classmethod
    def _split_commas(cls, value: Any) -> Any:
        """Read a comma-separated string (the environment form) as a list."""
        if isinstance(value, str):
            return [part.strip() for part in value.split(",") if part.strip()]
        return value

    @field_validator("data_dir", "model_dir", mode="after")
    @classmethod
    def _expand_home(cls, value: Path | None) -> Path | None:
        """Expand a leading ``~`` (``.env`` files are not shell-expanded)."""
        return value.expanduser() if value is not None else None

    def effective_workers(self) -> int:
        """Return the worker count; ``workers == 0`` means ``min(4, max(1, cpu_count // 2))``."""
        if self.workers > 0:
            return self.workers
        return min(4, max(1, (os.cpu_count() or 1) // 2))

    def effective_intra_op_threads(self) -> int:
        """Return threads per worker; unset means ``ceil(cpu_count / effective_workers())``."""
        if self.intra_op_threads is not None:
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
