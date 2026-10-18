"""The ``accurate`` optimiser, preset scan, prompts and speaker loss on CPU with stand-ins.

Runs wherever the ``builder`` extra is installed (no GPU, no weights); skipped otherwise.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest

torch = pytest.importorskip("torch")
for _dep in ("torchaudio", "librosa", "scipy", "soundfile", "onnx2torch", "onnxslim"):
    pytest.importorskip(_dep)

import soundfile as sf  # noqa: E402

from supertonic_server.builder import Progress  # noqa: E402
from supertonic_server.builder.extract.accurate import extract as accurate_extract  # noqa: E402
from supertonic_server.builder.extract.accurate.config import AccurateConfig  # noqa: E402
from supertonic_server.builder.extract.accurate.optimize import (  # noqa: E402
    nearest_preset,
    optimise,
    training_prompts,
)
from supertonic_server.builder.extract.accurate.speaker_loss import SpeakerLoss  # noqa: E402
from supertonic_server.builder.extract.base import NothingToSaveError  # noqa: E402

SR = 44100


class StopAfter:
    """A stop check that returns true from call ``n + 1`` on."""

    def __init__(self, n: int) -> None:
        self.n = n
        self.calls = 0

    def __call__(self) -> bool:
        self.calls += 1
        return self.calls > self.n


class StubTTS:
    """Waveform amplitude follows ``style_ttl[0, 0, 0]``; records which prompt ran."""

    device = torch.device("cpu")
    ramp = torch.linspace(-1.0, 1.0, 4410)

    def __init__(self) -> None:
        self.seen: list[Any] = []

    def forward(self, ids: Any, mask: Any, ttl: Any, latent: Any, latent_mask: Any) -> Any:
        self.seen.append(ids)
        return (ttl[:, 0, 0:1] * self.ramp).reshape(1, -1)

    def synthesize(self, prompt: Any, ttl: Any) -> Any:
        with torch.no_grad():
            return self.forward(prompt.ids, None, ttl, None, None).reshape(-1)


def loudness(wav: Any) -> Any:
    """Stand-in speaker loss: the target speaker is silence."""
    return (wav**2).mean()


def _prompts(n: int) -> list[Any]:
    return [SimpleNamespace(ids=i, mask=None, latent=None, latent_mask=None) for i in range(n)]


def _unit_ttl(seed: int = 0) -> Any:
    g = torch.Generator().manual_seed(seed)
    ttl = torch.randn(1, 50, 256, generator=g).abs()
    return ttl / ttl.norm(dim=-1, keepdim=True)


def _loss_of(ttl: Any) -> float:
    return float(loudness(StubTTS().forward(None, None, ttl, None, None)))


def _optimise(
    ttl: Any, stop: StopAfter, *, num_steps: int = 50, threshold: float = 0.0, n_prompts: int = 1
) -> tuple[Any, list[Progress], StubTTS]:
    events: list[Progress] = []
    tts = StubTTS()
    cfg = AccurateConfig(lr=1e-2, num_steps=num_steps, threshold=threshold, log_every=2)
    result = optimise(
        ttl,
        _loss_of(ttl),
        _prompts(n_prompts),
        tts,  # type: ignore[arg-type]
        loudness,
        cfg,
        on_progress=events.append,
        should_stop=stop,
    )
    return result, events, tts


def test_stop_keeps_best_so_far() -> None:
    ttl = _unit_ttl()
    result, events, _ = _optimise(ttl, StopAfter(3))
    assert result.stopped is True
    assert result.taken == 3
    assert result.loss < _loss_of(ttl)
    assert 1 <= result.best_step <= 3
    # the best vector is the one that produced the best loss
    assert _loss_of(result.ttl) == pytest.approx(result.loss, rel=1e-5)
    # every 2 steps, then a closing event for the odd step
    assert [e.step for e in events] == [2, 3]
    assert all(e.stage == "timbre" and e.total == 50 for e in events)
    assert events[-1].loss == pytest.approx(result.loss)


def test_stop_before_first_step_returns_start() -> None:
    ttl = _unit_ttl()
    result, events, tts = _optimise(ttl, StopAfter(0))
    assert result.stopped is True
    assert (result.taken, result.best_step) == (0, 0)
    assert torch.equal(result.ttl, ttl)
    assert result.loss == pytest.approx(_loss_of(ttl))
    assert events == [] and tts.seen == []


def test_runs_to_num_steps_and_rotates_texts_after_the_first() -> None:
    # upstream's scan consumes text 0, so the descent starts at text 1 and wraps
    result, _, tts = _optimise(_unit_ttl(), StopAfter(10**6), num_steps=5, n_prompts=3)
    assert result.stopped is False
    assert result.taken == 5
    assert tts.seen == [1, 2, 0, 1, 2]


def test_early_stop_at_threshold() -> None:
    result, _, _ = _optimise(_unit_ttl(), StopAfter(10**6), threshold=10.0)
    assert (result.taken, result.stopped) == (1, False)


def test_only_style_ttl_moves_and_start_is_untouched() -> None:
    ttl = _unit_ttl()
    before = ttl.clone()
    result, _, _ = _optimise(ttl, StopAfter(10**6), num_steps=4)
    assert torch.equal(ttl, before)
    assert not result.ttl.requires_grad


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


@pytest.fixture
def presets(tmp_path: Path) -> list[Path]:
    """F1 loudest (1), F2 middle (0.6), F3 silent (0): F3 is nearest to silence."""
    d = tmp_path / "voice_styles"
    d.mkdir()
    for name, row in (("F1", [1.0]), ("F2", [0.6, 0.8]), ("F3", [0.0, 1.0])):
        _write_style(d / f"{name}.json", row)
    return sorted(d.glob("*.json"))


def _scan(presets: list[Path], stop: StopAfter) -> tuple[Any, list[Progress], StubTTS]:
    events: list[Progress] = []
    tts = StubTTS()
    found = nearest_preset(
        presets,
        _prompts(1)[0],
        tts,  # type: ignore[arg-type]
        loudness,
        on_progress=events.append,
        should_stop=stop,
    )
    return found, events, tts


def test_preset_scan_finds_nearest_on_the_first_text(presets: list[Path]) -> None:
    found, events, tts = _scan(presets, StopAfter(10**6))
    assert found is not None
    path, loss, stopped = found
    assert (path.stem, stopped) == ("F3", False)
    assert loss == pytest.approx(0.0)
    assert [e.stage for e in events] == ["preset"] * 3
    assert [e.step for e in events] == [1, 2, 3] and events[0].total == 3
    assert tts.seen == [0, 0, 0]


def test_preset_scan_stop_keeps_nearest_so_far(presets: list[Path]) -> None:
    found, events, _ = _scan(presets, StopAfter(2))
    assert found is not None
    path, loss, stopped = found
    assert (path.stem, stopped) == ("F2", True)
    assert loss == pytest.approx(events[1].loss)
    assert len(events) == 2


def test_preset_scan_stop_before_any_is_none(presets: list[Path]) -> None:
    found, events, _ = _scan(presets, StopAfter(0))
    assert found is None
    assert events == []


class TextTTS:
    """Tokenises to one id per character; every sentence lasts 1.0 s under any dp."""

    device = torch.device("cpu")
    chunk = 3000
    latent_dim = 4

    def text(self, texts: list[str], lang: str) -> tuple[np.ndarray, np.ndarray]:
        lengths = [len(t) for t in texts]
        ids = np.zeros((len(texts), max(lengths)), dtype=np.int64)
        mask = np.zeros((len(texts), 1, max(lengths)), dtype=np.float32)
        for i, n in enumerate(lengths):
            ids[i, :n] = np.arange(1, n + 1) + 100 * i
            mask[i, 0, :n] = 1.0
        return ids, mask

    def seconds(self, ids: Any, mask: Any, dp: Any) -> Any:
        return torch.ones(ids.shape[0]) * (1.0 + 0.0 * dp.sum())


def test_training_prompts_longest_first_with_one_fixed_latent() -> None:
    texts = [["en", "bb"], ["en", "dddd"], ["en", "a"], ["en", "cccc"]]
    prompts = training_prompts(TextTTS(), texts, torch.zeros(1, 8, 16), seed=49)  # type: ignore[arg-type]
    lengths = [int(p.mask.sum()) for p in prompts]
    assert lengths == [4, 4, 2, 1]  # stable: "dddd" before "cccc"
    assert int(prompts[0].ids[0, 0]) == 101  # "dddd" was input row 1
    assert all(p.ids.shape == (1, 4) and p.mask.shape == (1, 1, 4) for p in prompts)
    frames = int((1.0 * SR + 3000 - 1) / 3000)  # upstream's sample_noisy_latent
    expected = np.random.RandomState(49).randn(1, 4, frames).astype(np.float32)
    assert all(p.latent is prompts[0].latent for p in prompts)
    assert np.array_equal(prompts[0].latent.numpy(), expected)
    assert prompts[0].latent_mask.shape == (1, 1, frames)


def test_training_prompts_reject_mixed_languages() -> None:
    with pytest.raises(ValueError, match="one language"):
        training_prompts(TextTTS(), [["en", "a"], ["ko", "b"]], torch.zeros(1, 8, 16), seed=1)  # type: ignore[arg-type]


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
