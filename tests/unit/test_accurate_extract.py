"""The ``accurate`` speaker loss and extractor orchestration, on CPU with stand-ins.

Runs wherever the ``builder`` extra is installed (no GPU, no weights); skipped otherwise.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest

torch = pytest.importorskip("torch")
for _dep in ("torchaudio", "librosa", "scipy", "soundfile", "onnx2torch", "onnxslim"):
    pytest.importorskip(_dep)

import soundfile as sf  # noqa: E402

from supertonic_server.builder import Progress  # noqa: E402
from supertonic_server.builder.extract.accurate import extract as accurate_extract  # noqa: E402
from supertonic_server.builder.extract.accurate.speaker_loss import SpeakerLoss  # noqa: E402
from supertonic_server.builder.extract.base import NothingToSaveError  # noqa: E402

SR = 44100


def _write_style(path: Path, first_row: list[float]) -> None:
    ttl = np.zeros((1, 50, 256), dtype=np.float32)
    ttl[..., : len(first_row)] = first_row
    dp = np.zeros((1, 8, 16), dtype=np.float32)
    dp[..., 0] = 1.0
    doc = {
        "style_ttl": {"data": ttl.tolist(), "dims": [1, 50, 256], "type": "float32"},
        "style_dp": {"data": dp.tolist(), "dims": [1, 8, 16], "type": "float32"},
    }
    path.write_text(json.dumps(doc), encoding="utf-8")


class StubEncoder:
    """ECAPA stand-in: the embedding is (mean |x|, max |x|, energy) of the 16 kHz signal."""

    def __init__(self) -> None:
        self.calls = 0

    def encode_batch(self, wavs: Any) -> Any:
        self.calls += 1
        a = wavs.abs()
        return torch.stack([a.mean(), a.amax(), (wavs**2).mean() + 0.1]).reshape(1, 1, 3)


def _tone(sr: int, amplitude: float = 0.5) -> Any:
    t = torch.arange(int(0.5 * sr)) / sr
    return (amplitude * torch.sin(2 * torch.pi * 220 * t)).reshape(1, -1)


def test_speaker_loss_is_one_minus_cosine_with_reference_embedded_once() -> None:
    encoder = StubEncoder()
    loss = SpeakerLoss(encoder, _tone(16000), torch.device("cpu"))
    assert encoder.calls == 1
    same = loss(_tone(SR))
    assert float(same) == pytest.approx(0.0, abs=1e-3)
    generated = (_tone(SR, 0.2) + 0.3).requires_grad_(True)
    value = loss(generated)
    value.backward()
    assert encoder.calls == 3
    assert 0.0 < float(value.detach()) <= 2.0
    assert generated.grad is not None and torch.isfinite(generated.grad).all()
    ref = torch.nn.functional.normalize(StubEncoder().encode_batch(_tone(16000)).reshape(-1), dim=0)
    resampled = loss.resample(generated.detach())
    gen = torch.nn.functional.normalize(StubEncoder().encode_batch(resampled).reshape(-1), dim=0)
    assert float(value.detach()) == pytest.approx(1 - float(ref @ gen), abs=1e-5)


def _model_dir(tmp_path: Path) -> Path:
    model = tmp_path / "model"
    (model / "voice_styles").mkdir(parents=True)
    _write_style(model / "voice_styles" / "F1.json", [1.0])
    return model


def _wav(tmp_path: Path) -> Path:
    path = tmp_path / "ref.wav"
    sf.write(str(path), _tone(SR).reshape(-1).numpy(), SR)
    return path


def test_stop_while_loading_is_nothing_to_save(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def no_ecapa(device: Any) -> Any:
        raise AssertionError("ECAPA must not load after a stop")

    monkeypatch.setattr(accurate_extract, "load_frozen_tts", lambda *a, **k: object())
    monkeypatch.setattr(accurate_extract, "load_ecapa", no_ecapa)
    events: list[Progress] = []
    with pytest.raises(NothingToSaveError):
        accurate_extract.extract_style(
            _wav(tmp_path),
            _model_dir(tmp_path),
            on_progress=events.append,
            should_stop=lambda: True,
            device="cpu",
        )
    assert [e.stage for e in events] == ["loading"]


@pytest.mark.parametrize("content", [None, b"not audio at all"])
def test_rejects_bad_wav_before_loading_models(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, content: bytes | None
) -> None:
    def no_load(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("models must not load for a bad reference")

    monkeypatch.setattr(accurate_extract, "load_frozen_tts", no_load)
    monkeypatch.setattr(accurate_extract, "load_ecapa", no_load)
    wav = tmp_path / "ref.wav"
    if content is not None:
        wav.write_bytes(content)
    with pytest.raises((FileNotFoundError, ValueError)):
        accurate_extract.extract_style(
            wav,
            _model_dir(tmp_path),
            on_progress=lambda p: None,
            should_stop=lambda: False,
            device="cpu",
        )


def test_shared_finish_reports_and_passes_extras(tmp_path: Path) -> None:
    from supertonic_server.builder.extract.common.finish import finish_with_duration
    from supertonic_server.builder.extract.duration_config import DurationConfig

    ttl, dp = torch.ones(1, 50, 256), torch.ones(1, 8, 16)
    events: list[Progress] = []
    checks = iter([False])  # no stop when timbre ended; one arrives as the rhythm stage starts
    style, report = finish_with_duration(
        "accurate",
        _wav(tmp_path),
        ttl,
        dp,
        [],
        object(),  # type: ignore[arg-type]  # a stop means the TTS is never used
        DurationConfig(),
        on_progress=events.append,
        should_stop=lambda: next(checks, True),
        preset_start="F1",
        preset_distance=0.74351,
        loss=0.2783,
        steps=200,
        stopped_early=False,
        similarity=0.7217,
        best_step=196,
    )
    assert [e.stage for e in events] == ["duration"]
    assert report["method"] == "accurate" and report["duration_status"] == "stopped"
    assert report["stopped_early"] is True  # a stopped duration stage counts
    assert (report["preset_distance"], report["loss"], report["steps"]) == (0.7435, 0.2783, 200)
    assert (report["similarity"], report["best_step"]) == (0.7217, 196)
    assert style["style_dp"]["dims"] == [1, 8, 16]
    assert style["metadata"]["source_file"] == "ref.wav"
