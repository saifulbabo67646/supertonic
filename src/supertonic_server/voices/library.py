"""Filesystem-backed voice library (read-only presets plus custom voices)."""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import tempfile
import threading
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from supertonic.core import Style
from supertonic.loader import load_voice_style_from_json_file

from supertonic_server.core.errors import ApiError
from supertonic_server.voices.models import Voice
from supertonic_server.voices.validation import validate_style

logger = logging.getLogger(__name__)

PRESET_IDS = frozenset({*(f"F{i}" for i in range(1, 6)), *(f"M{i}" for i in range(1, 6))})
_PRESET_PREVIEW_DIR = "_presets"


def _slug(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "voice"


def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
    """Write JSON to ``path`` via a temp file in the same directory."""
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


class VoiceLibrary:
    """Presets (``presets_dir/*.json``) and custom voices (``custom_dir/<id>/``).

    Safe to call from multiple threads; writes and the style cache are locked.
    """

    def __init__(self, presets_dir: Path, custom_dir: Path) -> None:
        self.presets_dir = presets_dir
        self.custom_dir = custom_dir
        self._lock = threading.RLock()
        self._cache: dict[str, Style] = {}
        self._voices: dict[str, Voice] = {}
        custom_dir.mkdir(parents=True, exist_ok=True)
        self._scan()

    def _scan(self) -> None:
        voices: dict[str, Voice] = {}
        for f in sorted(self.presets_dir.glob("*.json")):
            gender = {"F": "female", "M": "male"}.get(f.stem[:1].upper())
            voices[f.stem] = Voice(f.stem, f.stem, "preset", gender=gender)
        for meta in self.custom_dir.glob("*/voice.json"):
            try:
                v = Voice(**json.loads(meta.read_text(encoding="utf-8")))
            except (OSError, ValueError, TypeError):
                logger.warning("Skipping unreadable voice metadata: %s", meta)
                continue
            voices[v.id] = v
        self._voices = voices

    def list(self) -> list[Voice]:
        """Presets sorted by id, then custom voices by creation time."""
        with self._lock:
            vs = list(self._voices.values())
        presets = sorted((v for v in vs if v.kind == "preset"), key=lambda v: v.id)
        custom = sorted((v for v in vs if v.kind == "custom"), key=lambda v: (v.created_at, v.id))
        return presets + custom

    def get(self, voice_id: str) -> Voice:
        """Return a voice by exact id or raise 404 ``voice_not_found``."""
        with self._lock:
            v = self._voices.get(voice_id)
        if v is None:
            raise ApiError(404, "voice_not_found", f"Voice '{voice_id}' not found", param="voice")
        return v

    def resolve(self, ref: str) -> Voice:
        """Find a voice by id, case-insensitive id, then unique case-insensitive name."""
        voices = self.list()
        for v in voices:
            if v.id == ref:
                return v
        low = ref.lower()
        for v in voices:
            if v.id.lower() == low:
                return v
        named = [v for v in voices if v.name.lower() == low]
        if len(named) == 1:
            return named[0]
        if named:
            ids = ", ".join(v.id for v in named)
            raise ApiError(
                400, "ambiguous_voice", f"Voice '{ref}' matches several voices ({ids})", "voice"
            )
        avail = ", ".join(v.id for v in voices[:8])
        raise ApiError(
            404, "voice_not_found", f"Voice '{ref}' not found. Available: {avail}", "voice"
        )

    def _style_path(self, voice: Voice) -> Path:
        if voice.kind == "preset":
            return self.presets_dir / f"{voice.id}.json"
        return self.custom_dir / voice.id / "style.json"

    def style(self, voice_id: str) -> Style:
        """Load (and cache) the ``supertonic`` style for a voice."""
        voice = self.get(voice_id)
        with self._lock:
            cached = self._cache.get(voice.id)
            if cached is None:
                cached = load_voice_style_from_json_file(self._style_path(voice))
                self._cache[voice.id] = cached
            return cached

    def style_json(self, voice_id: str) -> dict[str, Any]:
        """Return the raw style JSON document for a voice."""
        path = self._style_path(self.get(voice_id))
        data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        return data

    def import_style(
        self,
        style: dict[str, Any],
        name: str,
        description: str = "",
        tags: Sequence[str] = (),
        source_note: str = "",
    ) -> Voice:
        """Validate and store a new custom voice; nothing is written if invalid."""
        validate_style(style)
        with self._lock:
            taken = {i.lower() for i in self._voices} | {i.lower() for i in PRESET_IDS}
            base = _slug(name)
            vid, n = base, 1
            while vid.lower() in taken:
                n += 1
                vid = f"{base}-{n}"
            voice = Voice(
                vid,
                name,
                "custom",
                description,
                list(tags),
                None,
                source_note,
                datetime.now(UTC).isoformat(),
            )
            folder = self.custom_dir / vid
            folder.mkdir(parents=True)
            try:
                _atomic_write(folder / "style.json", style)
                _atomic_write(folder / "voice.json", voice.to_dict())
            except BaseException:
                shutil.rmtree(folder, ignore_errors=True)
                raise
            self._voices[vid] = voice
            return voice

    def _custom(self, voice_id: str) -> Voice:
        voice = self.get(voice_id)
        if voice.kind == "preset":
            raise ApiError(400, "voice_read_only", f"Preset voice '{voice_id}' is read-only")
        return voice

    def update(
        self,
        voice_id: str,
        *,
        name: str | None = None,
        description: str | None = None,
        tags: Sequence[str] | None = None,
    ) -> Voice:
        """Edit metadata of a custom voice."""
        with self._lock:
            voice = self._custom(voice_id)
            new = Voice(**{**voice.to_dict()})
            if name is not None:
                new.name = name
            if description is not None:
                new.description = description
            if tags is not None:
                new.tags = list(tags)
            _atomic_write(self.custom_dir / new.id / "voice.json", new.to_dict())
            self._voices[new.id] = new
            return new

    def delete(self, voice_id: str) -> None:
        """Remove a custom voice and its files."""
        with self._lock:
            voice = self._custom(voice_id)
            shutil.rmtree(self.custom_dir / voice.id)
            del self._voices[voice.id]
            self._cache.pop(voice.id, None)

    def preview_path(self, voice_id: str, lang: str) -> Path:
        """Location of the cached preview WAV (not created here)."""
        voice = self.get(voice_id)
        base = self.custom_dir / (_PRESET_PREVIEW_DIR if voice.kind == "preset" else "")
        return base / voice.id / "previews" / f"{lang}.wav"
