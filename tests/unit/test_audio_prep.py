"""Tests for reference audio preparation and build models."""

from __future__ import annotations

import os
import subprocess
import tempfile
import wave
from pathlib import Path

import imageio_ffmpeg
import numpy as np
import pytest

from supertonic_server.audio.codec import to_pcm16
from supertonic_server.builder import (
    BuildRequest,
    Job,
    Progress,
    audio_prep,
    prepare_reference,
)
from supertonic_server.core.errors import ApiError

SR = 44100


def _speech(seconds: float, sr: int = SR, seed: int = 0) -> np.ndarray:
    """Amplitude-modulated 180 Hz tone with light noise, reading as continuous speech."""
    rng = np.random.default_rng(seed)
    t = np.arange(int(seconds * sr)) / sr
    env = 0.5 + 0.4 * np.sin(2 * np.pi * 3.0 * t)
    x = env * np.sin(2 * np.pi * 180 * t) + 0.05 * rng.standard_normal(len(t))
    return (0.6 * x).astype(np.float32)


def _wav_bytes(x: np.ndarray, sr: int = SR, channels: int = 1) -> bytes:
    pcm = to_pcm16(x)
    if channels == 2:
        pcm = np.repeat(np.frombuffer(pcm, dtype="<i2"), 2).tobytes()
    import io

    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm)
    return buf.getvalue()


def _encode(wav: bytes, fmt: list[str]) -> bytes:
    cmd = [imageio_ffmpeg.get_ffmpeg_exe(), "-nostdin", "-loglevel", "error", "-i", "pipe:0"]
    out = subprocess.run([*cmd, *fmt, "pipe:1"], input=wav, capture_output=True, check=True)
    return out.stdout


def _encode_mp4(wav: bytes) -> bytes:
    """AAC in MP4 with the moov atom at the end (ffmpeg default; needs a seekable input)."""
    exe = imageio_ffmpeg.get_ffmpeg_exe()
    with tempfile.TemporaryDirectory() as tmp:
        src, dst = Path(tmp, "in.wav"), Path(tmp, "out.m4a")
        src.write_bytes(wav)
        cmd = [exe, "-nostdin", "-loglevel", "error", "-i", str(src), "-c:a", "aac", str(dst)]
        subprocess.run(cmd, check=True, capture_output=True)
        return dst.read_bytes()


def _info(path: Path) -> tuple[int, int]:
    with wave.open(str(path), "rb") as w:
        return w.getframerate(), w.getnchannels()


def test_wav_mp3_webm_accepted(tmp_path: Path) -> None:
    wav = _wav_bytes(_speech(5.0))
    cases = [
        ("a.wav", wav),
        ("a.mp3", _encode(wav, ["-f", "mp3"])),
        ("a.webm", _encode(wav, ["-c:a", "libopus", "-f", "webm"])),
        ("a.m4a", _encode_mp4(wav)),
    ]
    for name, data in cases:
        p = prepare_reference([(name, data)], tmp_path / f"{name}.wav")
        assert 4.0 <= p.speech_seconds <= 5.2, name
        assert _info(p.path) == (44100, 1)


def test_stereo_8k_resampled(tmp_path: Path) -> None:
    data = _wav_bytes(_speech(5.0, sr=8000), sr=8000, channels=2)
    p = prepare_reference([("s.wav", data)], tmp_path / "o.wav")
    assert _info(p.path) == (44100, 1)
    assert 4.0 <= p.speech_seconds <= 5.2


def test_peak_normalised(tmp_path: Path) -> None:
    p = prepare_reference([("a.wav", _wav_bytes(_speech(4.0) * 0.2))], tmp_path / "o.wav")
    with wave.open(str(p.path), "rb") as w:
        x = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2")
    assert abs(int(np.abs(x).max()) / 32768 - 10 ** (-1 / 20)) < 0.01


def test_too_short(tmp_path: Path) -> None:
    with pytest.raises(ApiError) as e:
        prepare_reference([("a.wav", _wav_bytes(_speech(1.5)))], tmp_path / "o.wav")
    assert e.value.status == 400
    assert e.value.code == "invalid_reference_audio"
    assert "at least 3 s" in e.value.message


def test_8k_mono(tmp_path: Path) -> None:
    data = _wav_bytes(_speech(5.0, sr=8000), sr=8000)
    p = prepare_reference([("m.wav", data)], tmp_path / "o.wav")
    assert _info(p.path) == (44100, 1)
    assert 4.0 <= p.speech_seconds <= 5.2


def test_renamed_binary(tmp_path: Path) -> None:
    png = b"\x89PNG\r\n\x1a\n" + bytes(range(256)) * 40
    with pytest.raises(ApiError) as e:
        prepare_reference([("x.mp3", png)], tmp_path / "o.wav")
    assert (e.value.status, e.value.code) == (400, "invalid_reference_audio")


def test_total_upload_cap_before_decode(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*a: object, **k: object) -> None:
        raise AssertionError("decoded")

    monkeypatch.setattr(audio_prep, "_decode", boom)
    big = b"\0" * (audio_prep.MAX_UPLOAD_BYTES + 1)
    with pytest.raises(ApiError) as e:
        prepare_reference([("a.wav", big)], tmp_path / "o.wav")
    assert e.value.code == "invalid_reference_audio"
    assert "25 MB" in e.value.message


def test_decode_cap(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(audio_prep, "MAX_DECODE_S", 4.0)
    with pytest.raises(ApiError) as e:
        prepare_reference([("a.wav", _wav_bytes(_speech(6.0)))], tmp_path / "o.wav")
    assert e.value.code == "invalid_reference_audio"
    assert "longer than" in e.value.message


def test_long_name_truncated(tmp_path: Path) -> None:
    with pytest.raises(ApiError) as e:
        prepare_reference([("n" * 500 + ".wav", b"not audio")], tmp_path / "o.wav")
    assert len(e.value.message) < 400


def test_silent_file(tmp_path: Path) -> None:
    silent = _wav_bytes(np.zeros(SR * 5, dtype=np.float32))
    with pytest.raises(ApiError) as e:
        prepare_reference([("a.wav", silent)], tmp_path / "o.wav")
    assert e.value.code == "invalid_reference_audio"
    assert "0.0 s of speech" in e.value.message


def test_mostly_silent(tmp_path: Path) -> None:
    burst = _speech(0.2)
    gap = np.zeros(int(SR * 0.8), dtype=np.float32)
    x = np.concatenate([np.concatenate([burst, gap]) for _ in range(20)])[: SR * 20 - len(gap)]
    with pytest.raises(ApiError) as e:
        prepare_reference([("a.wav", _wav_bytes(x))], tmp_path / "o.wav")
    assert e.value.code == "invalid_reference_audio"
    assert "silence" in e.value.message


def test_garbage_file(tmp_path: Path) -> None:
    with pytest.raises(ApiError) as e:
        prepare_reference([("x.wav", b"not audio")], tmp_path / "o.wav")
    assert e.value.status == 400
    assert e.value.code == "invalid_reference_audio"


def test_file_count_limits(tmp_path: Path) -> None:
    data = _wav_bytes(_speech(4.0))
    for files in ([], [("a.wav", data)] * 4):
        with pytest.raises(ApiError) as e:
            prepare_reference(files, tmp_path / "o.wav")
        assert e.value.code == "invalid_reference_audio"


def test_multiple_files_concatenated(tmp_path: Path) -> None:
    files = [(f"f{i}.wav", _wav_bytes(_speech(4.0, seed=i))) for i in range(3)]
    p = prepare_reference(files, tmp_path / "o.wav")
    assert 11.0 <= p.speech_seconds <= 12.3
    assert p.source_names == ["f0.wav", "f1.wav", "f2.wav"]
    assert p.seconds > p.speech_seconds - 0.5


def test_too_long(tmp_path: Path) -> None:
    with pytest.raises(ApiError) as e:
        prepare_reference([("a.wav", _wav_bytes(_speech(70.0)))], tmp_path / "o.wav")
    assert e.value.code == "invalid_reference_audio"
    assert "at most 60 s" in e.value.message


def _request(**kw: object) -> BuildRequest:
    base: dict[str, object] = {
        "name": "Ana",
        "description": "",
        "tags": [],
        "source_note": "my own voice",
        "consent": True,
    }
    return BuildRequest(**{**base, **kw})  # type: ignore[arg-type]


def test_build_request_validation() -> None:
    req = _request()
    req.validate()
    assert req.method == "accurate"
    for kw, code, param in [
        ({"source_note": "  "}, "consent_required", "source_note"),
        ({"consent": False}, "consent_required", "consent"),
        ({"name": " "}, "invalid_request", "name"),
        ({"name": "x" * 101}, "invalid_request", "name"),
        ({"method": "slow"}, "invalid_request", "method"),
        ({"tags": ["calm", "a,b"]}, "invalid_request", "tags"),
    ]:
        with pytest.raises(ApiError) as e:
            _request(**kw).validate()
        assert (e.value.status, e.value.code, e.value.param) == (400, code, param)


def test_job_roundtrip() -> None:
    job = Job(
        id="j1",
        state="running",
        request=_request(method="fast"),
        created_at="t0",
        started_at="t1",
        finished_at=None,
        progress=Progress("timbre", 10, 3000, 0.2, "step", "t2"),
        voice_id=None,
        error=None,
        builder="local",
    )
    d = job.to_dict()
    assert d["request"]["method"] == "fast" and d["progress"]["total"] == 3000
    assert Job.from_dict(d) == job
    del d["request"]["method"]
    assert Job.from_dict(d).request.method == "accurate"


def test_undecodable_message_names_no_temp_path(tmp_path: Path) -> None:
    with pytest.raises(ApiError) as e:
        prepare_reference([("x.wav", b"not audio at all" * 100)], tmp_path / "o.wav")
    message = e.value.message
    for temp in {tempfile.gettempdir(), os.path.realpath(tempfile.gettempdir())}:
        assert temp not in message
    assert str(Path.home()) not in message
    assert message.startswith("x.wav: not decodable audio")


def test_tags_with_commas_are_refused() -> None:
    with pytest.raises(ApiError) as e:
        _request(tags=["news, calm"]).validate()
    assert e.value.message == "tags cannot contain commas"
