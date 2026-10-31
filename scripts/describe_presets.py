"""Measure pitch and pace of the built-in voices (F1-F5, M1-M5).

Synthesises the same two English sentences with every preset at speed 1.0 and prints a
Markdown table of median F0 (Hz) and speaking rate (syllables per second of speech).
Pitch comes from a plain numpy autocorrelation tracker; the rate counts the syllables of
the fixed text (vowel groups) over the summed length of the two sentence clips. Each voice
is rendered ``--repeats`` times and the medians are reported, because synthesis is not
fully deterministic.

The figures ground the descriptions in ``supertonic_server.voices.presets`` and the table
in ``docs/voices.md``. Run with ``uv run python scripts/describe_presets.py``.
"""

from __future__ import annotations

import argparse
import asyncio
import re
import statistics

import numpy as np
from supertonic.loader import load_voice_style_from_json_file

from supertonic_server.core.config import Settings
from supertonic_server.engine import PRIORITY_DEFAULT, Engine, load_engine
from supertonic_server.voices.presets import PRESETS

SENTENCES = (
    "The quick brown fox jumps over the lazy dog near the riverbank.",
    "Please call me back when you have a moment to talk about the plan.",
)
F0_MIN, F0_MAX = 60.0, 400.0
FRAME_S, HOP_S = 0.04, 0.01
VOICING_THRESHOLD = 0.5
STEPS = 8


def syllables(text: str) -> int:
    """Rough English syllable count: groups of vowels per word, at least one per word."""
    total = 0
    for word in re.findall(r"[a-z']+", text.lower()):
        groups = len(re.findall(r"[aeiouy]+", word))
        if word.endswith("e") and not word.endswith(("le", "ee")) and groups > 1:
            groups -= 1  # silent final e
        total += max(1, groups)
    return total


def median_f0(audio: np.ndarray, rate: int) -> float:
    """Median F0 (Hz) over voiced frames, by normalised autocorrelation."""
    frame, hop = int(FRAME_S * rate), int(HOP_S * rate)
    lag_min, lag_max = int(rate / F0_MAX), int(rate / F0_MIN)
    energies = [
        float(np.sqrt(np.mean(audio[i : i + frame] ** 2)))
        for i in range(0, len(audio) - frame, hop)
    ]
    floor = 0.1 * float(np.percentile(energies, 95)) if energies else 0.0
    f0s: list[float] = []
    for n, start in enumerate(range(0, len(audio) - frame, hop)):
        if energies[n] < floor:
            continue
        x = audio[start : start + frame].astype(np.float64)
        x = x - x.mean()
        spec = np.fft.rfft(x, 2 * frame)
        ac = np.fft.irfft(spec * np.conj(spec))[:frame]
        if ac[0] <= 0:
            continue
        ac = ac / ac[0]
        lag = lag_min + int(np.argmax(ac[lag_min:lag_max]))
        if ac[lag] >= VOICING_THRESHOLD:
            f0s.append(rate / lag)
    return float(np.median(f0s)) if f0s else float("nan")


async def measure(
    engine: Engine, voice_id: str, presets_dir: str, repeats: int
) -> tuple[float, float]:
    """Return (median F0 Hz, syllables per second) for one preset."""
    style = load_voice_style_from_json_file(f"{presets_dir}/{voice_id}.json")
    count = sum(syllables(s) for s in SENTENCES)
    pitches, rates = [], []
    for _ in range(repeats):
        clips = [
            await engine.synth(s, style, "en", 1.0, STEPS, PRIORITY_DEFAULT) for s in SENTENCES
        ]
        audio = np.concatenate(clips)
        pitches.append(median_f0(audio, engine.sample_rate))
        rates.append(count / (len(audio) / engine.sample_rate))
    return statistics.median(pitches), statistics.median(rates)


async def main() -> None:
    """Render every preset and print the table."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()
    engine, presets_dir = load_engine(Settings())
    print(f"sentences: {' '.join(SENTENCES)}")
    print(f"syllables: {sum(syllables(s) for s in SENTENCES)}, speed 1.0, steps {STEPS}\n")
    print("| id | name | description | median pitch (Hz) | pace (syllables/s) |")
    print("|---|---|---|---:|---:|")
    for voice_id, preset in PRESETS.items():
        f0, rate = await measure(engine, voice_id, str(presets_dir), args.repeats)
        print(f"| {voice_id} | {preset.name} | {preset.description} | {f0:.0f} | {rate:.2f} |")
    engine.scheduler.close()


if __name__ == "__main__":
    asyncio.run(main())
