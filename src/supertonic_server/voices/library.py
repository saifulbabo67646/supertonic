"""Filesystem-backed voice library (read-only presets plus custom voices)."""

from __future__ import annotations

import json
import logging
import os
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
from supertonic_server.voices.naming import check_name_free, slug, with_suffix
from supertonic_server.voices.presets import PRESET_IDS, PRESETS, preset_id_for_name
from supertonic_server.voices.validation import validate_style

logger = logging.getLogger(__name__)

_PRESET_PREVIEW_DIR = "_presets"


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
            preset = PRESETS.get(f.stem)
            if preset is None:  # a style file this server has no metadata for
                gender = {"F": "female", "M": "male"}.get(f.stem[:1].upper())
                voices[f.stem] = Voice(f.stem, f.stem, "preset", gender=gender)
                continue
            voices[f.stem] = Voice(
                f.stem, preset.name, "preset", preset.description, gender=preset.gender
            )
        for meta in self.custom_dir.glob("*/voice.json"):
            vid = meta.parent.name
            try:
                data = json.loads(meta.read_text(encoding="utf-8"))
                if data.get("id", vid) != vid:
                    logger.warning(
                        "Skipping voice folder %r: voice.json claims id %r", vid, data["id"]
                    )
                    continue
                v = Voice(**{**data, "id": vid, "kind": "custom"})
            except (OSError, ValueError, TypeError, AttributeError):
                logger.warning("Skipping unreadable voice metadata: %s", meta)
                continue
            if vid in voices:  # a folder named like a preset id
                logger.warning("Skipping voice folder %r: the id is taken by a preset", vid)
                continue
            voices[vid] = v
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
        """Find a voice by any reference a user may type.

        Order: exact id, built-in voice name (``"Mia"`` is ``F1``), id in any
        capitalisation, then a unique custom voice name; names are case-insensitive. A
        custom voice saved as ``mia`` before the built-in names existed keeps its exact id,
        but ``"Mia"`` means ``F1``.

        Raises:
            ApiError: 404 ``voice_not_found``; 400 ``ambiguous_voice`` when several custom
                voices share the name.
        """
        voices = self.list()
        for v in voices:
            if v.id == ref:
                return v
        preset_id = preset_id_for_name(ref)
        if preset_id is not None:
            with self._lock:
                preset = self._voices.get(preset_id)
            if preset is not None:
                return preset
        low = ref.lower()
        for v in voices:
            if v.id.lower() == low:
                return v
        named = [v for v in voices if v.kind == "custom" and v.name.lower() == low]
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
        extra: dict[str, Any] | None = None,
    ) -> Voice:
        """Validate and store a new custom voice; nothing is written if invalid.

        ``extra`` (build metadata) is stored as ``voice.json["build"]``.
        """
        validate_style(style)
        check_name_free(name)
        with self._lock:
            # Folders on disk count too: a leftover folder without valid metadata would
            # otherwise make every import under that name fail.
            on_disk = {p.name.lower() for p in self.custom_dir.iterdir()}
            # Built-in names too: an id ``mia`` would win over the name "Mia" for exact-id
            # lookups, so "Mia." becomes ``mia-2``.
            preset_names = {p.name.lower() for p in PRESETS.values()}
            taken = {i.lower() for i in (*self._voices, *PRESET_IDS)} | on_disk | preset_names
            base = slug(name)
            vid, n = base, 1
            while vid in taken:
                n += 1
                vid = with_suffix(base, n)
            voice = Voice(
                vid,
                name,
                "custom",
                description,
                list(tags),
                None,
                source_note,
                datetime.now(UTC).isoformat(),
                build=dict(extra) if extra is not None else None,
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
        """The custom voice with this exact id, for edits and deletes.

        A built-in name maps to its preset only so that, say, deleting "Mia" answers
        ``voice_read_only`` instead of 404; an existing exact id always wins.
        """
        with self._lock:
            exact = voice_id in self._voices
        preset_id = None if exact else preset_id_for_name(voice_id)
        voice = self.get(voice_id if preset_id is None else preset_id)
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
            if name is not None and name.strip().lower() != voice.name.strip().lower():
                check_name_free(name)
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

    def save_preview(self, voice_id: str, lang: str, wav: bytes) -> Path:
        """Store a rendered preview WAV atomically and return its path.

        Never recreates the folder of a voice deleted in the meantime: the voice must still
        exist (checked under the library lock) and, for custom voices, so must its folder.

        Raises:
            ApiError: 404 ``voice_not_found`` when the voice is gone.
        """
        with self._lock:
            voice = self.get(voice_id)
            path = self.preview_path(voice.id, lang)
            if voice.kind == "custom" and not (self.custom_dir / voice.id).is_dir():
                raise ApiError(
                    404, "voice_not_found", f"Voice '{voice_id}' not found", param="voice"
                )
            path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name, suffix=".tmp")
            try:
                with os.fdopen(fd, "wb") as fh:
                    fh.write(wav)
                os.replace(tmp, path)
            except BaseException:
                Path(tmp).unlink(missing_ok=True)
                raise
            return path
