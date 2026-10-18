"""Tests for PCM conversion, resampling, WAV headers and container encoding."""

from __future__ import annotations

import struct

import numpy as np
import pytest

from supertonic_server.audio import (
    ALLOWED_RATES,
    MIME,
    NATIVE_RATE,
    encode,
    resample,
    to_pcm16,
    wav_header,
)
from supertonic_server.core.errors import ApiError


def test_constants() -> None:
    assert NATIVE_RATE == 44100 and {16000, 22050, 24000, 44100} == ALLOWED_RATES
    assert MIME["mp3"] == "audio/mpeg" and MIME["pcm"] == "audio/pcm"
    assert set(MIME) == {"mp3", "opus", "aac", "flac", "wav", "pcm"}


def test_pcm16_roundtrip_and_clip() -> None:
    b = to_pcm16(np.array([0.0, 1.5, -1.5], dtype=np.float32))
    assert np.frombuffer(b, "<i2").tolist() == [0, 32767, -32767]


def test_resample_length() -> None:
    assert len(resample(np.zeros(44100, np.float32), 44100, 24000)) == 24000


def test_resample_identity() -> None:
    x = np.arange(10, dtype=np.float32)
    assert resample(x, 24000, 24000) is x


def test_streaming_wav_header() -> None:
    h = wav_header(24000, None)
    assert len(h) == 44 and h[4:8] == b"\xff\xff\xff\xff"
    assert h[40:44] == b"\xff\xff\xff\xff"


def test_sized_wav_header() -> None:
    h = wav_header(24000, 200)
    riff, size, wave = struct.unpack("<4sI4s", h[:12])
    assert (riff, size, wave) == (b"RIFF", 236, b"WAVE")
    channels, rate, byte_rate, align, bits = struct.unpack("<HIIHH", h[22:36])
    assert (channels, rate, byte_rate, align, bits) == (1, 24000, 48000, 2, 16)
    assert h[36:40] == b"data" and struct.unpack("<I", h[40:44])[0] == 200


@pytest.mark.parametrize(
    "fmt,magic",
    [
        ("mp3", (b"ID3", b"\xff\xf3", b"\xff\xfb")),
        ("flac", (b"fLaC",)),
        ("wav", (b"RIFF",)),
        ("opus", (b"OggS",)),
        ("aac", (b"\xff\xf1", b"\xff\xf9")),
    ],
)
def test_encode_formats(fmt: str, magic: tuple[bytes, ...]) -> None:
    assert encode(np.zeros(4410, np.float32), 44100, fmt).startswith(magic)


def test_encode_wav_and_pcm_payload() -> None:
    x = np.array([0.0, 0.5, -0.5], dtype=np.float32)
    assert encode(x, 24000, "pcm") == to_pcm16(x)
    wav = encode(x, 24000, "wav")
    assert wav[:44] == wav_header(24000, 6) and wav[44:] == to_pcm16(x)


def test_encode_unknown_format() -> None:
    with pytest.raises(ApiError) as e:
        encode(np.zeros(10, np.float32), 24000, "ogg")
    assert e.value.status == 400 and e.value.code == "invalid_response_format"


def test_encode_ffmpeg_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    import supertonic_server.audio.codec as codec

    # An unknown muxer makes ffmpeg exit non-zero.
    monkeypatch.setattr(codec, "_FFMPEG_ARGS", {**codec._FFMPEG_ARGS, "opus": ["-f", "nope"]})
    with pytest.raises(ApiError) as e:
        encode(np.zeros(10, np.float32), 24000, "opus")
    assert e.value.status == 500 and e.value.code == "encode_failed"
    assert e.value.type == "server_error" and "nope" in e.value.message


def _read_wav(data: bytes) -> tuple[int, int]:
    import io
    import wave

    with wave.open(io.BytesIO(data)) as w:
        return w.getnframes(), w.getframerate()


def test_finalize_streaming_wav() -> None:
    from supertonic_server.audio import finalize_wav

    pcm = to_pcm16(np.zeros(1234, dtype=np.float32))
    fixed = finalize_wav(wav_header(24000, None) + pcm)
    assert _read_wav(fixed) == (1234, 24000)
    assert struct.unpack_from("<I", fixed, 4)[0] == len(fixed) - 8
    assert fixed == wav_header(24000, len(pcm)) + pcm


def test_finalize_wav_with_extra_chunk() -> None:
    from supertonic_server.audio import finalize_wav

    pcm = to_pcm16(np.zeros(100, dtype=np.float32))
    header = wav_header(16000, None)
    extra = b"LIST" + struct.pack("<I", 5) + b"abcde" + b"\x00"  # odd size: padded
    data = header[:36] + extra + header[36:] + pcm
    assert _read_wav(finalize_wav(data)) == (100, 16000)


@pytest.mark.parametrize("data", [b"", b"RIFF\x00\x00\x00\x00WAVE", b"OggS" + b"\x00" * 40])
def test_finalize_wav_rejects_non_wav(data: bytes) -> None:
    from supertonic_server.audio import finalize_wav

    with pytest.raises(ValueError):
        finalize_wav(data)
