"""The pitch estimator and the pitch-gated start choice (plain numpy; runs everywhere)."""

from __future__ import annotations

import subprocess
import sys

import numpy as np
import pytest

from supertonic_server.builder.extract.common.pitch import (
    choose_start,
    describe_hz,
    log_distance,
    median_f0,
    pitch_report,
)


def harmonic(f0: float, sr: int, seconds: float = 2.0, amplitude: float = 0.3) -> np.ndarray:
    """A voice-like tone: the first five harmonics of ``f0`` at 1/k amplitude."""
    t = np.arange(int(seconds * sr)) / sr
    out: np.ndarray = amplitude * sum(np.sin(2 * np.pi * k * f0 * t) / k for k in range(1, 6))
    return out


def test_pitch_and_the_common_package_import_without_torch() -> None:
    code = (
        "import sys; sys.modules['torch'] = None\n"
        "import supertonic_server.builder.extract.common as common\n"
        "from supertonic_server.builder.extract.common.pitch import median_f0\n"
        "assert 'nearest_preset' in common.__all__ and median_f0 is not None\n"
    )
    subprocess.run([sys.executable, "-c", code], check=True)


@pytest.mark.parametrize("sr", [16000, 44100])
@pytest.mark.parametrize("f0", [110.0, 220.0])
def test_harmonic_tone_pitch_within_three_percent(f0: float, sr: int) -> None:
    found = median_f0(harmonic(f0, sr), sr)
    assert found is not None
    assert found == pytest.approx(f0, rel=0.03)


@pytest.mark.parametrize("sr", [16000, 44100])
def test_pitch_ignores_silence_around_speech(sr: int) -> None:
    gap = np.zeros(sr)
    found = median_f0(np.concatenate([gap, harmonic(129.0, sr, 1.0), gap]), sr)
    assert found == pytest.approx(129.0, rel=0.03)


@pytest.mark.parametrize("sr", [16000, 44100])
def test_silence_noise_and_short_clips_have_no_pitch(sr: int) -> None:
    rng = np.random.default_rng(0)
    assert median_f0(np.zeros(2 * sr), sr) is None
    assert median_f0(0.1 * rng.standard_normal(2 * sr), sr) is None
    assert median_f0(harmonic(110.0, sr, 0.05), sr) is None  # fewer than 10 voiced frames
    assert median_f0(np.array([np.nan] * sr), sr) is None


def test_log_distance_is_symmetric_and_octave_is_ln2() -> None:
    assert log_distance(200.0, 100.0) == pytest.approx(np.log(2))
    assert log_distance(100.0, 200.0) == log_distance(200.0, 100.0)
    assert log_distance(129.0, 129.0) == 0.0


# (loss, f0) per preset, as the scan measures them: M-like presets near 100-136 Hz,
# F-like presets near 190-230 Hz.
MALE_REF = 129.0
SCAN = [
    (0.40, 136.0),  # 0: M1
    (0.45, 98.0),  # 1: M2
    (0.30, 198.0),  # 2: F4, the lowest loss overall
    (0.32, 225.0),  # 3: F1
]


def test_male_reference_never_starts_from_a_female_preset() -> None:
    index, reason = choose_start(SCAN, MALE_REF)
    assert index == 0  # M1: within ±22% of 129 Hz and the lowest loss there
    assert "near 129 Hz" in reason


def test_female_reference_keeps_the_lowest_loss_among_female_presets() -> None:
    index, _ = choose_start(SCAN, 210.0)
    assert index == 2


def test_no_preset_near_the_reference_uses_the_two_nearest_by_pitch() -> None:
    # 70 Hz: nothing within ±22%; the two nearest by pitch are M2 (98) and M1 (136)
    index, reason = choose_start(SCAN, 70.0)
    assert index == 0  # M1 beats M2 on loss; F4 (lower loss) is not among the two
    assert "nearest by pitch" in reason


def test_unknown_reference_pitch_falls_back_to_lowest_loss() -> None:
    index, reason = choose_start(SCAN, None)
    assert index == 2
    assert "unclear" in reason


def test_presets_without_a_clear_pitch() -> None:
    assert choose_start([(0.5, None), (0.2, None)], MALE_REF)[0] == 1
    # an unpitched preset never competes once the reference has a pitch
    assert choose_start([(0.1, None), (0.5, 130.0), (0.4, 250.0)], MALE_REF)[0] == 1


def test_choose_start_needs_a_measured_preset() -> None:
    with pytest.raises(ValueError):
        choose_start([], MALE_REF)


def test_pitch_report_matches_within_tolerance() -> None:
    assert pitch_report(129.04, 202.0) == {
        "pitch_reference_hz": 129.0,
        "pitch_voice_hz": 202.0,
        "pitch_match": False,
    }
    assert pitch_report(129.0, 140.0)["pitch_match"] is True
    assert pitch_report(None, 140.0) == {
        "pitch_reference_hz": None,
        "pitch_voice_hz": 140.0,
        "pitch_match": None,
    }
    assert pitch_report(129.0, None)["pitch_match"] is None


def test_describe_hz() -> None:
    assert describe_hz(198.4) == "198 Hz"
    assert describe_hz(None) == "no clear pitch"
