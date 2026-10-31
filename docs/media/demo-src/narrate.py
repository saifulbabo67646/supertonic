"""Have Supertonic itself speak the narration: one WAV per line plus its word timings.

Usage: python narrate.py --server http://127.0.0.1:8801 [line ...]
Writes build/narration/<key>.wav and build/narration/timings.json.

The narration is tightened for pacing: the silence before and after each line is trimmed
and pauses between sentences are capped (the speech itself is untouched); the word timings
move with it so the captions stay in sync.
"""

from __future__ import annotations

import argparse
import array
import base64
import io
import json
import math
import urllib.request
import wave
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
OUT = HERE / "build" / "narration"
WINDOW_S = 0.01  # loudness is judged in 10 ms windows
SILENT_DB = -45.0
HEAD_S, TAIL_S, MAX_PAUSE_S = 0.05, 0.12, 0.5


def speak(server: str, body: dict[str, Any]) -> dict[str, Any]:
    req = urllib.request.Request(
        f"{server}/v1/tts/timestamps",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        result: dict[str, Any] = json.load(resp)
    return result


def tighten(
    wav_bytes: bytes, words: list[dict[str, Any]]
) -> tuple[bytes, list[dict[str, Any]], int]:
    """Trim silence at both ends and cap long pauses.

    Returns the WAV, the moved word timings and the new length in milliseconds.
    """
    with wave.open(io.BytesIO(wav_bytes)) as src:
        rate, width, channels = src.getframerate(), src.getsampwidth(), src.getnchannels()
        samples = array.array("h", src.readframes(src.getnframes()))
    assert width == 2 and channels == 1, "expected 16-bit mono WAV"
    step = int(rate * WINDOW_S)
    loud = []
    for i in range(0, len(samples), step):
        chunk = samples[i : i + step]
        rms = math.sqrt(sum(x * x for x in chunk) / max(1, len(chunk))) / 32768
        loud.append(20 * math.log10(rms) > SILENT_DB if rms > 0 else False)
    first = loud.index(True)
    last = len(loud) - 1 - loud[::-1].index(True)
    # keep[i]: whether window i survives; long silent runs inside keep only MAX_PAUSE_S
    keep = [False] * len(loud)
    head = int(HEAD_S / WINDOW_S)
    tail = int(TAIL_S / WINDOW_S)
    for i in range(max(0, first - head), min(len(loud), last + tail + 1)):
        keep[i] = True
    i = first
    cap = int(MAX_PAUSE_S / WINDOW_S)
    while i <= last:
        if not loud[i]:
            j = i
            while j <= last and not loud[j]:
                j += 1
            run = j - i
            if run > cap:
                drop_from = i + cap // 2
                for k in range(drop_from, drop_from + run - cap):
                    keep[k] = False
            i = j
        else:
            i += 1
    out = array.array("h")
    new_pos = []  # new time (s) of the start of each original window
    t = 0
    for i, kept in enumerate(keep):
        new_pos.append(t * WINDOW_S)
        if kept:
            out.extend(samples[i * step : (i + 1) * step])
            t += 1
    new_pos.append(t * WINDOW_S)

    def move(ms: int) -> int:
        w = min(len(new_pos) - 1, int(ms / 1000 / WINDOW_S))
        return round(new_pos[w] * 1000)

    moved = [{**w, "start_ms": move(w["start_ms"]), "end_ms": move(w["end_ms"])} for w in words]
    buf = io.BytesIO()
    with wave.open(buf, "wb") as dst:
        dst.setnchannels(1)
        dst.setsampwidth(2)
        dst.setframerate(rate)
        dst.writeframes(out.tobytes())
    return buf.getvalue(), moved, round(len(out) / rate * 1000)


def spoken(text: str, say: dict[str, str]) -> str:
    """The text as it is sent to the voice: `say` replaces words it would misread."""
    for written, sound in say.items():
        text = text.replace(written, sound)
    return text


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server", default="http://127.0.0.1:8801")
    parser.add_argument("only", nargs="*", help="line keys to (re)make; default all")
    args = parser.parse_args()
    script = json.loads((HERE / "narration.json").read_text(encoding="utf-8"))
    OUT.mkdir(parents=True, exist_ok=True)
    timings_path = OUT / "timings.json"
    timings = json.loads(timings_path.read_text()) if timings_path.exists() else {}
    for key, text in script["lines"].items():
        if args.only and key not in args.only:
            continue
        result = speak(
            args.server.rstrip("/"),
            {
                "text": spoken(text, script.get("say", {})),
                "voice": script["voice"],
                "language": script["language"],
                "speed": script["speed"],
                "total_steps": script["total_steps"],
                "response_format": "wav",
            },
        )
        raw = base64.b64decode(str(result["audio_base64"]))
        (OUT / f"{key}.raw.wav").write_bytes(raw)
        audio, words, length = tighten(raw, result["words"])
        (OUT / f"{key}.wav").write_bytes(audio)
        timings[key] = {"text": text, "duration_ms": length, "words": words}
        print(f"{key}: {int(result['duration_ms']) / 1000:.2f} s -> {length / 1000:.2f} s")
    timings_path.write_text(json.dumps(timings, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
