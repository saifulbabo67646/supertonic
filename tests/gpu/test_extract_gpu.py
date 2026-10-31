"""Real voice building on a CUDA GPU (needs the ``builder`` extra; run with ``-m gpu``).

Set ``SUPERTONIC_TEST_MODEL_DIR`` to an existing Supertonic 3 directory to skip the
download; otherwise the model is fetched into the default ``supertonic`` cache. The
reference recording is ``audio_samples/luna_reference.wav`` from ``Supertone/supertonic-3``.
"""

from __future__ import annotations

import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from supertonic_server.builder import Progress
from supertonic_server.builder.extract import extract_style
from supertonic_server.engine import Engine, Scheduler
from supertonic_server.voices import VoiceLibrary

pytestmark = pytest.mark.gpu

# Read at import: the autouse fixture in conftest clears SUPERTONIC_* before each test.
MODEL_DIR_ENV = os.environ.get("SUPERTONIC_TEST_MODEL_DIR")
LUNA = "audio_samples/luna_reference.wav"


@pytest.fixture(scope="module")
def tts() -> Any:
    """The real Supertonic 3 model (downloaded unless ``SUPERTONIC_TEST_MODEL_DIR`` is set)."""
    import supertonic

    kwargs: dict[str, Any] = {"model": "supertonic-3", "auto_download": True}
    if MODEL_DIR_ENV:
        kwargs["model_dir"] = MODEL_DIR_ENV
    return supertonic.TTS(**kwargs)


@pytest.fixture(scope="module")
def luna(tts: Any) -> Path:
    local = Path(tts.model_dir) / LUNA
    if local.exists():
        return local
    from huggingface_hub import hf_hub_download

    return Path(hf_hub_download("Supertone/supertonic-3", LUNA))


async def test_fast_builds_a_usable_voice(tts: Any, luna: Path, tmp_path: Path) -> None:
    import torch

    assert torch.cuda.is_available(), "the gpu test needs CUDA"
    torch.cuda.reset_peak_memory_stats()
    events: list[Progress] = []
    started = time.monotonic()
    wall = datetime.now(UTC)
    style, report = extract_style(
        "fast",
        luna,
        Path(tts.model_dir),
        on_progress=events.append,
        should_stop=lambda: False,
    )
    minutes = (time.monotonic() - started) / 60
    peak_gb = torch.cuda.max_memory_allocated() / 2**30
    print(f"\nfast: {minutes:.1f} min, peak VRAM {peak_gb:.2f} GB, report {json.dumps(report)}")
    print(f"fast stages: {_stage_times(wall, events)}")

    assert report["method"] == "fast"
    assert report["loss"] < 0.25
    assert report["stopped_early"] is False
    assert report["preset_start"] in {f"{g}{i}" for g in "FM" for i in range(1, 6)}
    _assert_pitch(report, events)
    stages = [e.stage for e in events]
    assert {"loading", "preset", "timbre", "duration"} <= set(stages)
    timbre = [e for e in events if e.stage == "timbre"]
    assert all(e.total is not None and e.loss is not None for e in timbre)

    for key, dims in (("style_ttl", [1, 50, 256]), ("style_dp", [1, 8, 16])):
        assert style[key]["dims"] == dims
        arr = np.asarray(style[key]["data"], dtype=np.float32)
        assert list(arr.shape) == dims
        assert np.allclose(np.linalg.norm(arr, axis=-1), 1.0, atol=1e-4)

    library = VoiceLibrary(Path(tts.model_dir) / "voice_styles", tmp_path / "custom")
    voice = library.import_style(json.loads(json.dumps(style)), "Luna", source_note="gpu test")
    engine = Engine(tts.model, Scheduler(workers=1, max_queue=4))
    audio, chunks = await engine.render(
        "Hello, this is a built voice.", library.style(voice.id), "en"
    )
    assert chunks
    assert np.isfinite(audio).all()
    assert float(np.abs(audio).max()) > 0.01


ACCURATE_GPU_STEPS = "200"  # a full build is 3000 steps (~90 min); 200 shows the descent


def _assert_valid_style(style: dict[str, Any], tmp_path: Path, model_dir: Path) -> None:
    for key, dims in (("style_ttl", [1, 50, 256]), ("style_dp", [1, 8, 16])):
        assert style[key]["dims"] == dims
        arr = np.asarray(style[key]["data"], dtype=np.float32)
        assert list(arr.shape) == dims
        assert np.isfinite(arr).all()
    library = VoiceLibrary(model_dir / "voice_styles", tmp_path / "custom")
    library.import_style(json.loads(json.dumps(style)), "Luna", source_note="gpu test")


def _stage_times(started: datetime, events: list[Progress]) -> str:
    """Seconds per stage from the progress timestamps (loading includes the first preset)."""

    def at(e: Progress) -> float:
        return (datetime.fromisoformat(e.at) - started).total_seconds()

    presets = [e for e in events if e.stage == "preset"]
    timbre = [e for e in events if e.stage == "timbre"]
    duration = [e for e in events if e.stage == "duration"]
    end = (datetime.now(UTC) - started).total_seconds()
    per_preset = (at(presets[-1]) - at(presets[0])) / max(1, len(presets) - 1)
    load = at(presets[0]) - per_preset
    steps = (timbre[-1].step or 0) - (timbre[0].step or 0)
    per_step = (at(timbre[-1]) - at(timbre[0])) / steps if steps else float("nan")
    timbre_s = at(timbre[-1]) - at(presets[-1])
    duration_s = end - at(duration[0]) if duration else 0.0
    return (
        f"loading {load:.0f} s, preset scan {at(presets[-1]) - load:.0f} s "
        f"({per_preset:.1f} s/preset), timbre {timbre_s:.0f} s ({per_step:.2f} s/step), "
        f"duration {duration_s:.0f} s"
    )


def _preset_dp(model_dir: Path, name: str) -> np.ndarray:
    doc = json.loads((model_dir / "voice_styles" / f"{name}.json").read_text(encoding="utf-8"))
    return np.asarray(doc["style_dp"]["data"], dtype=np.float32)


def _assert_pitch(report: dict[str, Any], events: list[Progress]) -> None:
    """Luna's pitch is measured, every preset shows its pitch, the voice keeps it."""
    assert report["pitch_reference_hz"] is not None
    assert report["pitch_voice_hz"] is not None
    assert report["pitch_match"] is True
    presets = [e.message for e in events if e.stage == "preset"]
    assert presets and all(m.endswith(" Hz") or m.endswith("no clear pitch") for m in presets)


def test_accurate_builds_a_closer_voice(
    tts: Any, luna: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import torch

    assert torch.cuda.is_available(), "the gpu test needs CUDA"
    monkeypatch.setenv("SUPERTONIC_BUILDER_ACCURATE_STEPS", ACCURATE_GPU_STEPS)
    model_dir = Path(tts.model_dir)
    torch.cuda.reset_peak_memory_stats()
    events: list[Progress] = []
    started = time.monotonic()
    wall = datetime.now(UTC)
    style, report = extract_style(
        "accurate", luna, model_dir, on_progress=events.append, should_stop=lambda: False
    )
    minutes = (time.monotonic() - started) / 60
    peak_gb = torch.cuda.max_memory_allocated() / 2**30
    print(f"\naccurate: {minutes:.1f} min, peak VRAM {peak_gb:.2f} GB, report {json.dumps(report)}")
    print(f"accurate stages: {_stage_times(wall, events)}")

    assert report["method"] == "accurate"
    assert report["preset_start"] in {f"{g}{i}" for g in "FM" for i in range(1, 6)}
    # As upstream: the best loss is over the rotating training texts, the preset loss is
    # the scan's on text 0, so the two are on different sentences.
    assert report["loss"] < report["preset_distance"]
    assert report["similarity"] == round(1 - report["loss"], 4)
    assert report["stopped_early"] is False
    assert 1 <= report["steps"] <= int(ACCURATE_GPU_STEPS)
    presets = [e for e in events if e.stage == "preset"]
    assert len(presets) == 10 and all(e.loss is not None for e in presets)
    _assert_pitch(report, events)
    timbre = [e for e in events if e.stage == "timbre"]
    assert timbre and all(e.total == int(ACCURATE_GPU_STEPS) for e in timbre)
    assert [e.step for e in timbre[:2]] == [8, 16]
    assert any(e.stage == "duration" for e in events)

    _assert_valid_style(style, tmp_path, model_dir)
    dp = np.asarray(style["style_dp"]["data"], dtype=np.float32)
    assert not np.allclose(dp, _preset_dp(model_dir, report["preset_start"]))


def test_accurate_finish_now_saves_best_so_far(
    tts: Any, luna: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SUPERTONIC_BUILDER_ACCURATE_STEPS", ACCURATE_GPU_STEPS)
    stop_file = tmp_path / "STOP"
    events: list[Progress] = []

    def on_progress(p: Progress) -> None:
        events.append(p)
        if p.stage == "timbre":
            stop_file.touch()  # what POST /v1/jobs/{id}/finish does

    style, report = extract_style(
        "accurate",
        luna,
        Path(tts.model_dir),
        on_progress=on_progress,
        should_stop=stop_file.exists,
    )
    print(f"\naccurate (finish now): report {json.dumps(report)}")
    assert report["stopped_early"] is True
    assert report["steps"] == 8
    assert report["duration_status"] == "stopped"
    assert report["loss"] < report["preset_distance"]  # different texts, as above
    assert report["similarity"] == round(1 - report["loss"], 4)
    _assert_valid_style(style, tmp_path, Path(tts.model_dir))
