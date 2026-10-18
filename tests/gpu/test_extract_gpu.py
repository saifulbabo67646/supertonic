"""Real voice building on a CUDA GPU (needs the ``builder`` extra; run with ``-m gpu``).

Set ``SUPERTONIC_TEST_MODEL_DIR`` to an existing Supertonic 3 directory to skip the
download; otherwise the model is fetched into the default ``supertonic`` cache. The
reference recording is ``audio_samples/luna_reference.wav`` from ``Supertone/supertonic-3``.
"""

from __future__ import annotations

import json
import os
import time
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

    assert report["method"] == "fast"
    assert report["loss"] < 0.25
    assert report["stopped_early"] is False
    assert report["preset_start"] in {f"{g}{i}" for g in "FM" for i in range(1, 6)}
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
