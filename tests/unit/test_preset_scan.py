"""The pitch-gated preset scan, on CPU with a fake TTS and a fake loss.

Runs wherever the ``builder`` extra is installed (no GPU, no weights); skipped otherwise.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest

torch = pytest.importorskip("torch")
for _dep in ("librosa", "scipy", "soundfile", "onnx2torch", "onnxslim"):
    pytest.importorskip(_dep)

from supertonic_server.builder import Progress  # noqa: E402
from supertonic_server.builder.extract.common.preset_scan import nearest_preset  # noqa: E402

SR = 44100
PROMPT = SimpleNamespace(ids=None, mask=None, latent=None, latent_mask=None)
# name: (f0 in Hz, fake loss). F4 has the lowest loss overall, as in the reported bug.
PRESETS = {"F1": (225.0, 0.32), "F4": (198.0, 0.30), "M1": (136.0, 0.40), "M2": (98.0, 0.45)}


class ToneTTS:
    """Speaks a harmonic tone at ``style_ttl[0, 0, 0]`` Hz.

    The fake loss of the last waveform is ``style_ttl[0, 0, 1]`` (see :meth:`loss`).
    """

    device = torch.device("cpu")

    def __init__(self) -> None:
        self.last_loss = 0.0

    def synthesize(self, prompt: Any, ttl: Any) -> Any:
        f0 = float(ttl[0, 0, 0])
        self.last_loss = float(ttl[0, 0, 1])
        t = torch.arange(SR) / SR
        return 0.3 * sum(torch.sin(2 * torch.pi * k * f0 * t) / k for k in range(1, 6))

    def loss(self, wav: Any) -> Any:
        return torch.tensor(self.last_loss)


def _write(path: Path, f0: float, loss: float) -> None:
    ttl = np.zeros((1, 50, 256), dtype=np.float32)
    ttl[0, 0, :2] = (f0, loss)
    dp = np.ones((1, 8, 16), dtype=np.float32)
    doc = {
        "style_ttl": {"data": ttl.tolist(), "dims": [1, 50, 256], "type": "float32"},
        "style_dp": {"data": dp.tolist(), "dims": [1, 8, 16], "type": "float32"},
    }
    path.write_text(json.dumps(doc), encoding="utf-8")


@pytest.fixture
def presets(tmp_path: Path) -> list[Path]:
    for name, (f0, loss) in PRESETS.items():
        _write(tmp_path / f"{name}.json", f0, loss)
    return sorted(tmp_path.glob("*.json"))


def _scan(
    presets: list[Path], reference_f0: float | None, stop_after: int = 10**6
) -> tuple[Any, list[Progress]]:
    events: list[Progress] = []
    calls = iter(range(10**7))
    tts = ToneTTS()
    found = nearest_preset(
        presets,
        PROMPT,  # type: ignore[arg-type]
        tts,  # type: ignore[arg-type]
        tts.loss,
        on_progress=events.append,
        should_stop=lambda: next(calls) >= stop_after,
        reference_f0=reference_f0,
    )
    return found, events


def test_male_reference_never_picks_a_female_preset(
    presets: list[Path], caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO):
        found, events = _scan(presets, 129.0)
    assert found is not None
    path, loss, stopped = found
    assert (path.stem, stopped) == ("M1", False)
    assert loss == pytest.approx(0.40, abs=1e-6)
    assert "start preset M1" in caplog.text and "near 129 Hz" in caplog.text


def test_progress_shows_every_preset_with_its_pitch(presets: list[Path]) -> None:
    _, events = _scan(presets, 129.0)
    assert [e.stage for e in events] == ["preset"] * 4
    assert events[1].message == "F4: 0.3000 · 198 Hz"
    assert [e.message.split(":")[0] for e in events] == ["F1", "F4", "M1", "M2"]


def test_female_reference_keeps_lowest_loss(presets: list[Path]) -> None:
    found, _ = _scan(presets, 210.0)
    assert found is not None and found[0].stem == "F4"


def test_no_preset_near_uses_the_two_nearest_by_pitch(presets: list[Path]) -> None:
    found, _ = _scan(presets, 70.0)  # M2 (98) and M1 (136) are the nearest; M1 has less loss
    assert found is not None and found[0].stem == "M1"


def test_unknown_reference_pitch_keeps_todays_choice(presets: list[Path]) -> None:
    found, _ = _scan(presets, None)
    assert found is not None and found[0].stem == "F4"


def test_stop_chooses_among_presets_measured_so_far(presets: list[Path]) -> None:
    found, events = _scan(presets, 129.0, stop_after=2)  # F1 and F4 only
    assert len(events) == 2
    assert found is not None
    path, _, stopped = found
    assert stopped is True and path.stem in {"F1", "F4"}
    # neither is near 129 Hz: the two nearest by pitch compete, F4 has the lower loss
    assert path.stem == "F4"
