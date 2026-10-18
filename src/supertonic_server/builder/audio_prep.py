"""Decode, trim, validate and merge reference recordings into one clean 44.1 kHz WAV."""

from __future__ import annotations

import subprocess
import tempfile
import wave
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import imageio_ffmpeg
import numpy as np

from supertonic_server.audio.codec import NATIVE_RATE, to_pcm16
from supertonic_server.audio.timing import FRAME_MS, SILENCE_DB, speech_bounds
from supertonic_server.core.errors import ApiError
from supertonic_server.core.limits import MAX_FILES, MAX_UPLOAD_BYTES
from supertonic_server.core.scrub import scrub_paths

MIN_SPEECH_S = 3.0
MAX_SPEECH_S = 60.0
MAX_SILENCE_RATIO = 0.7
GAP_S = 0.3
MAX_DECODE_S = 600.0
PEAK_DBFS = -1.0
_DECODE_TIMEOUT_S = 120
_STDERR_TAIL = 200
_NAME_MAX = 100


@dataclass(frozen=True)
class PreparedAudio:
    """A prepared reference recording on disk."""

    path: Path
    seconds: float
    speech_seconds: float
    source_names: list[str]


def _invalid(message: str) -> ApiError:
    return ApiError(400, "invalid_reference_audio", message, param="files")


def _decoder_unavailable(exc: Exception) -> ApiError:
    message = f"audio decoder unavailable: {scrub_paths(str(exc))}"
    return ApiError(500, "internal_error", message, type_="server_error")


def _label(name: str) -> str:
    """Client file name, truncated for echoing in messages."""
    return name if len(name) <= _NAME_MAX else name[:_NAME_MAX] + "..."


def _decode(index: int, name: str, data: bytes) -> np.ndarray:
    """Decode ``data`` to mono float32 at 44.1 kHz via ffmpeg.

    The bytes go to a private temp file (named by us, never from ``name``) because formats such
    as m4a keep their index at the end and cannot be read from a pipe.
    """
    label = _label(name)
    try:
        exe = imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as exc:
        raise _decoder_unavailable(exc) from None
    with tempfile.TemporaryDirectory(prefix="supertonic-ref-") as tmp:
        src = Path(tmp) / f"ref-{index}"
        src.write_bytes(data)
        cmd = [
            exe, "-nostdin", "-hide_banner", "-loglevel", "error",
            "-i", str(src), "-vn", "-t", str(MAX_DECODE_S),
            "-ac", "1", "-ar", str(NATIVE_RATE), "-f", "f32le", "pipe:1",
        ]  # fmt: skip
        try:
            proc = subprocess.run(cmd, capture_output=True, timeout=_DECODE_TIMEOUT_S, check=False)
        except subprocess.TimeoutExpired:
            raise _invalid(f"{label}: decoding timed out") from None
        except OSError as exc:
            raise _decoder_unavailable(exc) from None
    if proc.returncode != 0 or len(proc.stdout) < 4:
        # ffmpeg names the temp file it read: scrub before cutting so no partial path is left
        tail = scrub_paths(proc.stderr.decode("utf-8", "replace")).strip()[-_STDERR_TAIL:]
        raise _invalid(f"{label}: not decodable audio" + (f" ({tail})" if tail else ""))
    usable = len(proc.stdout) // 4 * 4
    audio = np.frombuffer(proc.stdout[:usable], dtype="<f4").astype(np.float32)
    if len(audio) >= MAX_DECODE_S * NATIVE_RATE:
        raise _invalid(f"{label}: longer than {MAX_DECODE_S / 60:g} minutes")
    return np.nan_to_num(audio, nan=0.0, posinf=0.0, neginf=0.0)


def _speech_frames(audio: np.ndarray) -> tuple[int, int]:
    """Return (non-silent frames, total frames) using the same rule as ``speech_bounds``."""
    frame = NATIVE_RATE * FRAME_MS // 1000
    frames = len(audio) // frame
    if frames == 0:
        return 0, 0
    x = audio[: frames * frame].astype(np.float64).reshape(frames, frame)
    rms = np.sqrt(np.mean(x * x, axis=1))
    peak = float(rms.max())
    if peak <= 0.0:
        return 0, frames
    return int(np.count_nonzero(rms >= peak * 10 ** (-SILENCE_DB / 20))), frames


def prepare_reference(files: Sequence[tuple[str, bytes]], out_path: Path) -> PreparedAudio:
    """Merge 1-3 recordings into one normalised mono 16-bit 44.1 kHz WAV at ``out_path``.

    Each file is decoded, edge-trimmed, then joined with 0.3 s gaps. Speech duration must be
    within 3-60 s and at most 70 % of the trimmed frames may be silent.

    Raises:
        ApiError: 400 ``invalid_reference_audio`` with the reason.
    """
    if not 1 <= len(files) <= MAX_FILES:
        raise _invalid(f"provide 1 to {MAX_FILES} audio files")
    if sum(len(d) for _, d in files) > MAX_UPLOAD_BYTES:
        raise _invalid(f"total upload exceeds {MAX_UPLOAD_BYTES // (1024 * 1024)} MB")
    gap = np.zeros(int(GAP_S * NATIVE_RATE), dtype=np.float32)
    pieces: list[np.ndarray] = []
    speech_frames = total_frames = 0
    for i, (name, data) in enumerate(files):
        audio = _decode(i, name, data)
        start, end = speech_bounds(audio, NATIVE_RATE)
        audio = audio[start:end]
        loud, frames = _speech_frames(audio)
        speech_frames += loud
        total_frames += frames
        if i:
            pieces.append(gap)
        pieces.append(audio)
    speech_s = speech_frames * FRAME_MS / 1000
    if speech_s < MIN_SPEECH_S:
        raise _invalid(
            f"reference has {speech_s:.1f} s of speech; need at least {MIN_SPEECH_S:g} s"
        )
    if speech_s > MAX_SPEECH_S:
        raise _invalid(f"reference has {speech_s:.1f} s of speech; at most {MAX_SPEECH_S:g} s")
    ratio = 1.0 - speech_frames / max(1, total_frames)
    if ratio > MAX_SILENCE_RATIO:
        raise _invalid(
            f"reference is {ratio:.0%} silence; at most {MAX_SILENCE_RATIO:.0%} is allowed"
        )
    merged = np.concatenate(pieces)
    peak = float(np.max(np.abs(merged)))
    if peak > 0.0:
        merged = merged * (10 ** (PEAK_DBFS / 20) / peak)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(out_path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(NATIVE_RATE)
        w.writeframes(to_pcm16(merged))
    return PreparedAudio(
        path=out_path,
        seconds=len(merged) / NATIVE_RATE,
        speech_seconds=speech_s,
        source_names=[n for n, _ in files],
    )
