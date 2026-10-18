"""MCP tools that let agents discover voices and generate speech files locally."""

from __future__ import annotations

import base64
import io
import logging
import os
import secrets
import wave
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from supertonic_server.audio import finalize_wav
from supertonic_server.mcp.client import SupertonicApiError, SupertonicClient

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "http://127.0.0.1:8787"
DEFAULT_OUTPUT_DIR = "./supertonic-output"
SPEAK_FORMATS = ("wav", "mp3", "flac", "opus", "aac", "pcm")
TIMESTAMP_FORMATS = ("wav", "mp3")
PCM_DEFAULT_RATE = 24000
REQUEST_TIMEOUT = 300.0


def _fail(exc: SupertonicApiError) -> ToolError:
    return ToolError(f"{exc.message} (code: {exc.code})")


def _target(output_dir: Path, voice: str, fmt: str, output_path: str | None) -> Path:
    """Resolve where to save: the explicit path, else a fresh unique file in ``output_dir``."""
    if output_path:
        return Path(output_path).expanduser().absolute()
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in voice)
    while True:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        path = output_dir / f"{safe}-{stamp}-{secrets.token_hex(3)}.{fmt}"
        if not path.exists():
            return path.absolute()


def _save(path: Path, data: bytes) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return str(path)


def _finished_wav(data: bytes, sample_rate: int | None) -> tuple[bytes, int]:
    """Fix the streamed WAV's size fields; return the file and its duration in ms.

    The duration comes from the fixed header (frame count) and ``X-Sample-Rate``.
    """
    try:
        fixed = finalize_wav(data)
        with wave.open(io.BytesIO(fixed)) as w:
            frames, rate = w.getnframes(), sample_rate or w.getframerate()
    except (ValueError, EOFError, wave.Error) as exc:
        raise ToolError(f"The server returned an unreadable WAV file: {exc}") from exc
    return fixed, round(frames / rate * 1000)


def build_server(client: SupertonicClient, output_dir: Path) -> MCPServer:
    """Build the MCP server.

    Args:
        client: Client for a running Supertonic server.
        output_dir: Directory where generated audio files are saved by default.
    """
    server = MCPServer(
        "supertonic",
        instructions=(
            "Text-to-speech with Supertonic 3. Call list_voices and list_languages to "
            "discover options, then speak to generate an audio file saved on this machine."
        ),
    )

    @server.tool()
    async def list_languages() -> list[dict[str, str]]:
        """List supported languages.

        Returns a list of ``{code, name}``. Pass ``code`` as the ``language`` argument of
        ``speak`` and ``preview_voice``.
        """
        try:
            langs = await client.languages()
        except SupertonicApiError as exc:
            raise _fail(exc) from exc
        return [{"code": lang["code"], "name": lang["name"]} for lang in langs]

    @server.tool()
    async def list_voices(kind: str | None = None, tag: str | None = None) -> list[dict[str, Any]]:
        """List available voices.

        Args:
            kind: Optional filter, ``"preset"`` (built in) or ``"custom"`` (user-imported).
            tag: Optional filter, keep only voices carrying this tag.

        Returns a list of ``{id, name, kind, gender, tags, description}``. Pass ``id`` as the
        ``voice`` argument of ``speak`` and ``preview_voice``.
        """
        try:
            voices = await client.voices(kind, tag)
        except SupertonicApiError as exc:
            raise _fail(exc) from exc
        keys = ("id", "name", "kind", "gender", "tags", "description")
        return [{k: v.get(k) for k in keys} for v in voices]

    @server.tool()
    async def speak(
        text: str,
        voice: str,
        language: str = "en",
        speed: float = 1.05,
        format: str = "wav",
        output_path: str | None = None,
        timestamps: bool = False,
    ) -> dict[str, Any]:
        """Generate speech and save it as an audio file on the machine running this server.

        Args:
            text: Text to speak.
            voice: Voice id from ``list_voices`` (e.g. ``"F1"``).
            language: Language code from ``list_languages``. Default ``"en"``.
            speed: Speaking rate, 0.7 to 2.0 (out of range is an error). Default 1.05.
            format: ``wav``, ``mp3``, ``flac``, ``opus``, ``aac`` or ``pcm`` (raw 16-bit
                little-endian mono at 24000 Hz). With ``timestamps`` only ``wav`` or ``mp3``.
            output_path: Where to save. ``~`` is expanded and missing folders are created. An
                existing file at exactly this path is overwritten. If omitted, a uniquely named
                file is created in the server's output directory.
            timestamps: If true, also return estimated word timings in ``words``.

        Returns ``{path, duration_ms, voice, language}`` plus ``words`` when ``timestamps``.
        ``path`` is the absolute path of the saved file. ``duration_ms`` is the audio length in
        milliseconds; it is ``null`` for compressed formats (mp3, flac, opus, aac) without
        ``timestamps``, since those are not decoded. ``words`` is a list of
        ``{text, start_ms, end_ms}``; timings are estimated, not forced-aligned, and for
        Japanese each item is one character.
        """
        if format not in SPEAK_FORMATS:
            raise ToolError(f"format must be one of {list(SPEAK_FORMATS)}, got '{format}'")
        if timestamps and format not in TIMESTAMP_FORMATS:
            raise ToolError("format must be wav or mp3 when timestamps is true")
        try:
            if timestamps:
                data = await client.timestamps(text, voice, language, speed, format)
                saved = _save(
                    _target(output_dir, data["voice"], format, output_path),
                    base64.b64decode(data["audio_base64"]),
                )
                return {
                    "path": saved,
                    "duration_ms": data["duration_ms"],
                    "voice": data["voice"],
                    "language": data["language"],
                    "words": data["words"],
                }
            speech = await client.speech(text, voice, language, speed, format)
        except SupertonicApiError as exc:
            raise _fail(exc) from exc
        audio = speech.audio
        duration: int | None = None
        if format == "wav":
            audio, duration = _finished_wav(audio, speech.sample_rate)
        elif format == "pcm":
            rate = speech.sample_rate or PCM_DEFAULT_RATE
            duration = round(len(audio) / 2 / rate * 1000)
        saved = _save(_target(output_dir, speech.voice, format, output_path), audio)
        return {"path": saved, "duration_ms": duration, "voice": speech.voice, "language": language}

    @server.tool()
    async def preview_voice(voice: str, language: str = "en") -> dict[str, str]:
        """Save a short sample of a voice so it can be auditioned.

        Args:
            voice: Voice id from ``list_voices``.
            language: Language code from ``list_languages``. Default ``"en"``.

        Returns ``{path}``, the absolute path of a WAV file saved on this machine.
        """
        try:
            audio = await client.preview(voice, language)
        except SupertonicApiError as exc:
            raise _fail(exc) from exc
        name = f"preview-{voice}-{language}"
        path = _target(output_dir, name, "wav", None)
        return {"path": _save(path, audio)}

    return server


def main() -> None:
    """Run the MCP server over stdio, configured from ``SUPERTONIC_*`` environment variables."""
    logging.basicConfig(level=logging.INFO)
    base_url = os.environ.get("SUPERTONIC_BASE_URL", DEFAULT_BASE_URL)
    api_key = os.environ.get("SUPERTONIC_API_KEY") or None
    output_dir = Path(os.environ.get("SUPERTONIC_MCP_OUTPUT_DIR", DEFAULT_OUTPUT_DIR))
    http = httpx.AsyncClient(base_url=base_url, timeout=REQUEST_TIMEOUT)
    build_server(SupertonicClient(http, api_key), output_dir.expanduser().absolute()).run("stdio")
