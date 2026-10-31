"""Stop semantics of the real extractor code, on CPU with tiny stand-ins for the models.

Runs wherever the ``builder`` extra is installed (no GPU, no weights); skipped otherwise.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest

torch = pytest.importorskip("torch")
for _dep in ("librosa", "scipy", "soundfile", "onnx2torch", "onnxslim"):
    pytest.importorskip(_dep)

import soundfile as sf  # noqa: E402

from supertonic_server.builder import Progress  # noqa: E402
from supertonic_server.builder.extract.accurate import extract as accurate_extract  # noqa: E402
from supertonic_server.builder.extract.accurate.config import AccurateConfig  # noqa: E402
from supertonic_server.builder.extract.base import NothingToSaveError  # noqa: E402
from supertonic_server.builder.extract.common.duration import duration_inversion  # noqa: E402
from supertonic_server.builder.extract.common.finish import (  # noqa: E402
    PITCH_PROMPTS,
    _voice_f0,
    finish_with_duration,
)
from supertonic_server.builder.extract.common.preset_scan import nearest_preset  # noqa: E402
from supertonic_server.builder.extract.duration_config import DurationConfig  # noqa: E402
from supertonic_server.builder.extract.fast import extract as fast_extract  # noqa: E402
from supertonic_server.builder.extract.fast.config import FastConfig, TimbreConfig  # noqa: E402
from supertonic_server.builder.extract.fast.invert_ttl import invert  # noqa: E402
from supertonic_server.builder.extract.fast.wavlm_loss import (  # noqa: E402
    layer_stats,
    style_loss,
    to_wavlm_rate,
)

LAYER = 4
SR = 44100
PROMPT = SimpleNamespace(ids=None, mask=None, latent=None, latent_mask=None)


class StopAfter:
    """A stop check that returns true from call ``n + 1`` on."""

    def __init__(self, n: int) -> None:
        self.n = n
        self.calls = 0

    def __call__(self) -> bool:
        self.calls += 1
        return self.calls > self.n


def _wavlm(wav16: Any, output_hidden_states: bool = True) -> Any:
    """Stand-in WavLM: every layer is the waveform itself, so stats are its mean/std."""
    return SimpleNamespace(hidden_states=[wav16.unsqueeze(-1)] * (LAYER + 1))


class StubTTS:
    """Waveform amplitude follows ``style_ttl[0, 0, 0]``, differentiably."""

    device = torch.device("cpu")
    ramp = torch.linspace(-1.0, 1.0, 4410)

    def forward(self, ids: Any, mask: Any, ttl: Any, latent: Any, latent_mask: Any) -> Any:
        return (ttl[:, 0, 0:1] * self.ramp).reshape(1, -1)

    def synthesize(self, prompt: Any, ttl: Any) -> Any:
        with torch.no_grad():
            return self.forward(None, None, ttl, None, None).reshape(-1)


ZERO_TARGET = (torch.zeros(1, 1), torch.zeros(1, 1))


def _unit_ttl(seed: int = 0) -> Any:
    g = torch.Generator().manual_seed(seed)
    ttl = torch.randn(1, 50, 256, generator=g).abs()
    return ttl / ttl.norm(dim=-1, keepdim=True)


def _loss_of(ttl: Any) -> float:
    wav = StubTTS().forward(None, None, ttl, None, None)
    return float(style_loss(layer_stats(_wavlm, to_wavlm_rate(wav), LAYER), ZERO_TARGET))


def _invert(ttl: Any, stop: StopAfter, max_steps: int = 50) -> tuple[Any, list[Progress]]:
    events: list[Progress] = []
    cfg = TimbreConfig(threshold=0.0, lr=1e-2, max_steps=max_steps, progress_every=1)
    result = invert(
        ZERO_TARGET,
        ttl,
        _loss_of(ttl),
        [PROMPT],
        StubTTS(),  # type: ignore[arg-type]
        _wavlm,
        cfg,
        on_progress=events.append,
        should_stop=stop,
    )
    return result, events


def test_timbre_stop_keeps_best_so_far() -> None:
    ttl = _unit_ttl()
    result, events = _invert(ttl, StopAfter(3))
    assert result.stopped is True
    assert result.taken == 3
    assert result.loss < _loss_of(ttl)
    assert 1 <= result.steps <= 3
    assert torch.allclose(result.ttl.norm(dim=-1), torch.ones(1, 50), atol=1e-5)
    assert abs(_loss_of(result.ttl) - result.loss) < 0.05
    assert [e.step for e in events] == [1, 2, 3]
    assert all(e.stage == "timbre" and e.total == 50 for e in events)


def test_timbre_stop_before_first_step_returns_start() -> None:
    ttl = _unit_ttl()
    result, events = _invert(ttl, StopAfter(0))
    assert result.stopped is True
    assert (result.taken, result.steps) == (0, 0)
    assert torch.equal(result.ttl, ttl)
    assert result.loss == pytest.approx(_loss_of(ttl))
    assert events == []


def test_timbre_without_stop_runs_to_max_steps() -> None:
    result, _ = _invert(_unit_ttl(), StopAfter(10**6), max_steps=5)
    assert result.stopped is False
    assert result.taken == 5


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
    """F1 far (amplitude 1), F2 middle (0.6), F3 nearest (0) from the zero target."""
    d = tmp_path / "voice_styles"
    d.mkdir()
    for name, row in (("F1", [1.0]), ("F2", [0.6, 0.8]), ("F3", [0.0, 1.0])):
        _write_style(d / f"{name}.json", row)
    return sorted(d.glob("*.json"))


def _scan(presets: list[Path], stop: StopAfter) -> tuple[Any, list[Progress]]:
    events: list[Progress] = []
    found = nearest_preset(
        presets,
        PROMPT,  # type: ignore[arg-type]
        StubTTS(),  # type: ignore[arg-type]
        lambda wav: style_loss(layer_stats(_wavlm, to_wavlm_rate(wav), LAYER), ZERO_TARGET),
        on_progress=events.append,
        should_stop=stop,
    )
    return found, events


def test_preset_scan_finds_nearest(presets: list[Path]) -> None:
    found, events = _scan(presets, StopAfter(10**6))
    assert found is not None
    path, _, stopped = found
    assert (path.stem, stopped) == ("F3", False)
    assert [e.stage for e in events] == ["preset"] * 3


def test_preset_scan_stop_keeps_nearest_so_far(presets: list[Path]) -> None:
    found, events = _scan(presets, StopAfter(2))
    assert found is not None
    path, distance, stopped = found
    assert (path.stem, stopped) == ("F2", True)
    assert distance == pytest.approx(events[1].loss)
    assert len(events) == 2


def test_preset_scan_stop_before_any_is_none(presets: list[Path]) -> None:
    found, events = _scan(presets, StopAfter(0))
    assert found is None
    assert events == []


def _pulses(rate_hz: float, seconds: float, sr: int) -> np.ndarray:
    """A 200 Hz tone whose loudness pulses ``rate_hz`` times a second (syllable-like)."""
    t = np.arange(int(seconds * sr)) / sr
    envelope = 0.5 * (1 - np.cos(2 * np.pi * rate_hz * t))
    return (0.5 * envelope * np.sin(2 * np.pi * 200 * t)).astype(np.float32)


class DurationTTS:
    """Predicted length follows ``style_dp[0, 0, 0]``; synthesis always pulses at 3/s."""

    device = torch.device("cpu")

    def seconds(self, ids: Any, mask: Any, dp: Any) -> Any:
        return (2.0 + 0.5 * dp[:, 0, 0]).reshape(1)

    def predict_seconds(self, prompt: Any, dp: Any) -> float:
        return float(self.seconds(None, None, dp).reshape(()))

    def synthesize_at_own_length(self, prompt: Any, ttl: Any, dp: Any) -> np.ndarray:
        return _pulses(3.0, self.predict_seconds(prompt, dp), SR)


def _dp_start() -> Any:
    dp = torch.zeros(1, 8, 16)
    dp[..., 0] = 0.6
    dp[..., 1] = 0.8
    return dp


def _duration(stop: StopAfter) -> tuple[Any, dict[str, Any], list[Progress]]:
    events: list[Progress] = []
    cfg = DurationConfig(invert_steps=5, max_iters=3)
    dp, report = duration_inversion(
        _pulses(4.5, 3.0, 16000),
        torch.zeros(1, 50, 256),
        _dp_start(),
        [PROMPT],
        DurationTTS(),  # type: ignore[arg-type]
        cfg,
        on_progress=events.append,
        should_stop=stop,
    )
    return dp, report, events


def test_duration_stop_before_start_keeps_start_dp() -> None:
    dp, report, events = _duration(StopAfter(0))
    assert report["status"] == "stopped"
    assert report["rate_ref"] is not None
    assert torch.equal(dp, _dp_start())
    assert events == []


def test_duration_stop_mid_fit_keeps_best_so_far() -> None:
    # 1 pre-start check, then 2 of the first fit's 5 steps before the stop
    dp, report, events = _duration(StopAfter(3))
    assert report["status"] == "stopped"
    assert report["iters"] == 0
    assert torch.equal(dp, _dp_start())
    assert report["rate_final"] == report["rate_start"]
    assert events == []


def test_duration_stop_after_an_iteration_keeps_its_result() -> None:
    # pre-start check + one full fit (5 steps) + 2 steps into the second fit
    dp, report, events = _duration(StopAfter(1 + 5 + 2))
    assert report["status"] == "stopped"
    assert report["iters"] == 1
    assert [e.step for e in events] == [1]
    assert torch.allclose(dp.norm(dim=-1), torch.ones(1, 8), atol=1e-5)


def _model_dir(tmp_path: Path) -> Path:
    model = tmp_path / "model"
    (model / "voice_styles").mkdir(parents=True)
    _write_style(model / "voice_styles" / "F1.json", [1.0])
    return model


def _wav(tmp_path: Path) -> Path:
    path = tmp_path / "ref.wav"
    sf.write(str(path), _pulses(4.0, 2.0, SR), SR)
    return path


def test_fast_stop_while_loading_is_nothing_to_save(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def no_wavlm(device: Any) -> Any:
        raise AssertionError("WavLM must not load after a stop")

    monkeypatch.setattr(fast_extract, "load_frozen_tts", lambda *a, **k: object())
    monkeypatch.setattr(fast_extract, "load_wavlm", no_wavlm)
    events: list[Progress] = []
    with pytest.raises(NothingToSaveError):
        fast_extract.extract_style(
            _wav(tmp_path),
            _model_dir(tmp_path),
            on_progress=events.append,
            should_stop=lambda: True,
            device="cpu",
        )
    assert [e.stage for e in events] == ["loading"]


@pytest.mark.parametrize("content", [None, b"not audio at all"])
def test_fast_rejects_bad_wav_before_loading_models(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, content: bytes | None
) -> None:
    def no_load(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("models must not load for a bad reference")

    monkeypatch.setattr(fast_extract, "load_frozen_tts", no_load)
    wav = tmp_path / "ref.wav"
    if content is not None:
        wav.write_bytes(content)
    with pytest.raises((FileNotFoundError, ValueError)):
        fast_extract.extract_style(
            wav,
            _model_dir(tmp_path),
            on_progress=lambda p: None,
            should_stop=lambda: False,
            device="cpu",
        )


SMALL_DURATION = DurationConfig(invert_steps=5, max_iters=3)


class StopFlag:
    """The STOP file: absent until :meth:`press` (Finish now)."""

    def __init__(self) -> None:
        self.pressed = False

    def press(self) -> None:
        self.pressed = True

    def __call__(self) -> bool:
        return self.pressed


class BuildTTS(DurationTTS):
    """``DurationTTS`` plus what the method pipelines ask of the frozen TTS."""

    def build_prompts(self, texts: Any, dp: Any) -> list[Any]:
        return [PROMPT]


def _timbre_finished_now(flag: StopFlag, ttl_arg: int) -> Any:
    """A timbre stage during which Finish now is pressed: it stops after 2 steps."""

    def run(*args: Any, **kwargs: Any) -> Any:
        flag.press()
        ttl = args[ttl_arg]
        return SimpleNamespace(ttl=ttl, loss=0.3, steps=2, taken=2, best_step=2, stopped=True)

    return run


def _run_method(
    method: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, flag: StopFlag
) -> Any:
    model = _model_dir(tmp_path)
    for name in ("F4", "M1"):
        _write_style(model / "voice_styles" / f"{name}.json", [1.0])
    chosen = (model / "voice_styles" / "F1.json", 0.4, False)
    events: list[Progress] = []
    if method == "fast":
        mod: Any = fast_extract
        monkeypatch.setattr(mod, "load_wavlm", lambda device: _wavlm)
        monkeypatch.setattr(mod, "target_from_file", lambda *a: ZERO_TARGET)
        monkeypatch.setattr(mod, "invert", _timbre_finished_now(flag, ttl_arg=1))
        config: Any = FastConfig(duration=SMALL_DURATION)
    else:
        mod = accurate_extract
        monkeypatch.setattr(mod, "load_ecapa", lambda device: object())
        monkeypatch.setattr(mod, "SpeakerLoss", lambda *a: object())
        monkeypatch.setattr(mod, "load_reference16", lambda *a: None)
        monkeypatch.setattr(mod, "training_prompts", lambda *a: [PROMPT])
        monkeypatch.setattr(mod, "optimise", _timbre_finished_now(flag, ttl_arg=0))
        config = dataclasses.replace(AccurateConfig(), duration=SMALL_DURATION)
    monkeypatch.setattr(mod, "load_frozen_tts", lambda *a, **k: BuildTTS())
    monkeypatch.setattr(mod, "nearest_preset", lambda *a, **k: chosen)
    _, report = mod.extract_style(
        _wav(tmp_path),
        model,
        on_progress=events.append,
        should_stop=flag,
        device="cpu",
        config=config,
    )
    return report, events


@pytest.mark.parametrize("method", ["fast", "accurate"])
def test_finish_during_timbre_still_matches_rhythm(
    method: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    report, events = _run_method(method, tmp_path, monkeypatch, StopFlag())
    assert report["stopped_early"] is True
    assert report["duration_status"] != "stopped"
    assert report["rate_final"] is not None
    # the reference (_wav) and the stand-in voice are both 200 Hz tones
    assert report["pitch_reference_hz"] == pytest.approx(200.0, rel=0.03)
    assert report["pitch_match"] is True
    duration_steps = [e.step for e in events if e.stage == "duration"]
    assert duration_steps[0] == 0 and max(s or 0 for s in duration_steps) >= 1


def _finish(wav: Path, stop: Any, reference_f0: float | None = None) -> dict[str, Any]:
    _, report = finish_with_duration(
        "fast",
        wav,
        torch.zeros(1, 50, 256),
        _dp_start(),
        [PROMPT],
        BuildTTS(),  # type: ignore[arg-type]
        SMALL_DURATION,
        on_progress=lambda p: None,
        should_stop=stop,
        preset_start="F1",
        preset_distance=0.4,
        loss=0.3,
        steps=5,
        stopped_early=False,
        reference_f0=reference_f0,
    )
    return report


def test_finish_during_rhythm_alone_stops_rhythm(tmp_path: Path) -> None:
    # timbre ended on its own (no STOP yet); the STOP arrives as rhythm starts
    report = _finish(_wav(tmp_path), StopAfter(1))
    assert report["duration_status"] == "stopped"
    assert report["stopped_early"] is True


def test_no_finish_runs_rhythm_to_its_end(tmp_path: Path) -> None:
    report = _finish(_wav(tmp_path), StopAfter(10**6))
    assert report["duration_status"] != "stopped"
    assert report["stopped_early"] is False


def test_finish_reports_the_pitch_of_the_final_style(tmp_path: Path) -> None:
    # BuildTTS speaks a 200 Hz tone
    far = _finish(_wav(tmp_path), StopAfter(10**6), reference_f0=129.0)
    assert far["pitch_reference_hz"] == 129.0
    assert far["pitch_voice_hz"] == pytest.approx(200.0, rel=0.03)
    assert far["pitch_match"] is False
    near = _finish(_wav(tmp_path), StopAfter(10**6), reference_f0=190.0)
    assert near["pitch_match"] is True
    unknown = _finish(_wav(tmp_path), StopAfter(10**6))
    assert unknown["pitch_reference_hz"] is None and unknown["pitch_match"] is None


class ToneTTS:
    """Speaks each prompt as a harmonic tone at the prompt's own ``f0``; counts the calls."""

    def __init__(self, fail_on: float | None = None) -> None:
        self.spoken: list[float] = []
        self.fail_on = fail_on

    def synthesize_at_own_length(self, prompt: Any, ttl: Any, dp: Any) -> np.ndarray:
        if prompt.f0 == self.fail_on:
            raise RuntimeError("CUDA out of memory")
        self.spoken.append(prompt.f0)
        t = np.arange(SR) / SR
        return 0.3 * sum(np.sin(2 * np.pi * k * prompt.f0 * t) / k for k in range(1, 6))


def _tone_prompts(*f0s: float) -> list[Any]:
    return [SimpleNamespace(f0=f0) for f0 in f0s]


def test_voice_pitch_pools_the_first_prompts() -> None:
    tts = ToneTTS()
    style = torch.zeros(1, 50, 256), _dp_start()
    found = _voice_f0(_tone_prompts(100.0, 130.0, 130.0, 135.0, 300.0), *style, tts)  # type: ignore[arg-type]
    assert found == pytest.approx(130.0, rel=0.03)  # prompts[0] alone would say 100 Hz
    assert tts.spoken == [100.0, 130.0, 130.0, 135.0]  # only the first PITCH_PROMPTS
    assert PITCH_PROMPTS == 4
    fewer = _voice_f0(_tone_prompts(100.0, 130.0), *style, ToneTTS())  # type: ignore[arg-type]
    assert fewer is not None and 100.0 <= fewer <= 130.0
    assert _voice_f0([], *style, ToneTTS()) is None  # type: ignore[arg-type]


def test_voice_pitch_failure_is_none(caplog: pytest.LogCaptureFixture) -> None:
    style = torch.zeros(1, 50, 256), _dp_start()
    tts = ToneTTS(fail_on=130.0)
    assert _voice_f0(_tone_prompts(100.0, 130.0, 135.0), *style, tts) is None  # type: ignore[arg-type]
    assert "could not measure" in caplog.text
