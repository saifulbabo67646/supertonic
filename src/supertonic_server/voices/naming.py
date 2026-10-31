"""Custom voice ids and names: slugs, numbered suffixes and the reserved built-in names."""

from __future__ import annotations

import re

from supertonic_server.core.errors import voice_name_taken
from supertonic_server.voices.presets import is_reserved

MAX_SLUG_LENGTH = 64
"""Longest custom voice id (folder name)."""

# Device names Windows refuses as file or folder names, whatever the extension.
_WINDOWS_RESERVED = frozenset(
    {
        "con",
        "prn",
        "aux",
        "nul",
        *(f"com{i}" for i in range(1, 10)),
        *(f"lpt{i}" for i in range(1, 10)),
    }
)


def slug(name: str) -> str:
    """A filesystem-safe id: lowercase ``a-z0-9-``, at most 64 characters, never reserved."""
    out = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    out = out[:MAX_SLUG_LENGTH].rstrip("-") or "voice"
    if out in _WINDOWS_RESERVED:
        out = f"{out}-voice"
    return out


def with_suffix(base: str, n: int) -> str:
    """``base`` plus ``-<n>``, trimmed so the result stays within the id length limit."""
    suffix = f"-{n}"
    return base[: MAX_SLUG_LENGTH - len(suffix)].rstrip("-") + suffix


def check_name_free(name: str) -> None:
    """Refuse a custom voice name that equals a built-in voice's id or name.

    Raises:
        ApiError: 409 ``voice_name_taken``.
    """
    if is_reserved(name):
        raise voice_name_taken(name)
