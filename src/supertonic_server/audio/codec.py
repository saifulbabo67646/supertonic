"""PCM conversion, resampling, WAV headers and container encoding."""

from __future__ import annotations

import logging
import struct
import subprocess

import imageio_ffmpeg
import numpy as np
import soxr

from supertonic_server.core.errors import ApiError

logger = logging.getLogger(__name__)

NATIVE_RATE = 44100
"""Sample rate of Supertonic 3 output (Hz)."""

ALLOWED_RATES = {16000, 22050, 24000, 44100}
"""Output sample rates clients may request."""

MIME = {
    "mp3": "audio/mpeg",
    "opus": "audio/ogg",
    "aac": "audio/aac",
    "flac": "audio/flac",
    "wav": "audio/wav",
    "pcm": "audio/pcm",
}
"""Content type for each supported ``response_format``."""

_UNKNOWN_SIZE = 0xFFFFFFFF
_STDERR_TAIL = 500
_FFMPEG_ARGS: dict[str, list[str]] = {
    "mp3": ["-f", "mp3"],
    "opus": ["-c:a", "libopus", "-f", "ogg"],
    "aac": ["-c:a", "aac", "-f", "adts"],
    "flac": ["-f", "flac"],
}


def resample(x: np.ndarray, src: int, dst: int) -> np.ndarray:
    """Resample mono float audio from ``src`` Hz to ``dst`` Hz (returns ``x`` when equal)."""
    if src == dst:
        return x
    out: np.ndarray = soxr.resample(np.asarray(x, dtype=np.float32), src, dst)
    return out.astype(np.float32, copy=False)


def to_pcm16(x: np.ndarray) -> bytes:
    """Convert float audio in [-1, 1] (clipped) to little-endian signed 16-bit PCM bytes."""
    clipped = np.clip(np.asarray(x, dtype=np.float32), -1.0, 1.0)
    return (clipped * 32767.0).astype("<i2").tobytes()


def wav_header(sample_rate: int, data_len: int | None) -> bytes:
    """Build a 44-byte PCM16 mono WAV header.

    Args:
        sample_rate: Sample rate in Hz.
        data_len: Size of the PCM payload in bytes, or ``None`` for a stream of unknown
            length (both size fields are then ``0xFFFFFFFF``).
    """
    if data_len is None:
        riff_size = data_size = _UNKNOWN_SIZE
    else:
        riff_size, data_size = 36 + data_len, data_len
    return struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        riff_size,
        b"WAVE",
        b"fmt ",
        16,  # fmt chunk size
        1,  # PCM
        1,  # mono
        sample_rate,
        sample_rate * 2,  # byte rate
        2,  # block align
        16,  # bits per sample
        b"data",
        data_size,
    )


def encode(x: np.ndarray, sample_rate: int, fmt: str) -> bytes:
    """Encode mono float audio as ``fmt`` (one of :data:`MIME`).

    ``pcm`` and ``wav`` are produced in-process; the other formats are piped through the
    ffmpeg binary bundled with ``imageio-ffmpeg``.

    Raises:
        ApiError: 400 ``invalid_response_format`` for an unknown format, 500
            ``encode_failed`` when ffmpeg fails.
    """
    if fmt not in MIME:
        raise ApiError(
            400,
            "invalid_response_format",
            f"Unsupported response_format {fmt!r}; expected one of {sorted(MIME)}",
            param="response_format",
        )
    pcm = to_pcm16(x)
    if fmt == "pcm":
        return pcm
    if fmt == "wav":
        return wav_header(sample_rate, len(pcm)) + pcm
    return _ffmpeg(pcm, sample_rate, fmt)


def _ffmpeg(pcm: bytes, sample_rate: int, fmt: str) -> bytes:
    cmd = [
        imageio_ffmpeg.get_ffmpeg_exe(),
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "s16le",
        "-ar",
        str(sample_rate),
        "-ac",
        "1",
        "-i",
        "pipe:0",
        *_FFMPEG_ARGS[fmt],
        "pipe:1",
    ]
    try:
        proc = subprocess.run(cmd, input=pcm, capture_output=True, check=False)
    except OSError as exc:
        logger.error("could not run ffmpeg: %s", exc)
        raise ApiError(
            500, "encode_failed", f"Could not run ffmpeg: {exc}", type_="server_error"
        ) from exc
    if proc.returncode != 0 or not proc.stdout:
        tail = proc.stderr.decode("utf-8", "replace").strip()[-_STDERR_TAIL:]
        logger.error("ffmpeg %s encode failed (exit %s): %s", fmt, proc.returncode, tail)
        raise ApiError(
            500,
            "encode_failed",
            f"Encoding to {fmt} failed: {tail or f'ffmpeg exited with {proc.returncode}'}",
            type_="server_error",
        )
    return proc.stdout
