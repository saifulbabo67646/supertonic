"""Smoke test of a running server: ``supertonic-server check``.

Three requests that prove an install works end to end, the same on every operating system
(no curl or PowerShell quoting): the health check, a speech file and word timestamps. Used
by people and by coding agents following ``AGENTS.md``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

MODEL_ID = "supertonic-3"
SPEECH_TEXT = "Hello from Supertonic."
TIMESTAMP_TEXT = "Hello there, world."
TIMESTAMP_WORDS = ["Hello", "there,", "world."]
# The built-in voice Mia by its id: ids work on every server version, names only on newer ones,
# and `check` may be pointed at an older server that an agent reuses.
VOICE = "F1"
TIMEOUT_S = 120.0


class CheckFailed(Exception):
    """Raised when the server answers, but not as a working Supertonic server should."""


@dataclass(frozen=True)
class Report:
    """What the smoke test found."""

    version: str
    voices: int
    builder: str
    speech_path: Path
    speech_bytes: int
    words: list[str]
    duration_ms: int


def _json(response: httpx.Response, what: str) -> dict[str, Any]:
    """Return the JSON object of a successful response, or raise ``CheckFailed``."""
    if response.status_code != 200:
        raise CheckFailed(f"{what}: HTTP {response.status_code}: {response.text[:300]}")
    try:
        body = response.json()
    except ValueError as exc:
        raise CheckFailed(f"{what}: the answer is not JSON") from exc
    if not isinstance(body, dict):
        raise CheckFailed(f"{what}: the answer is not a JSON object")
    return body


def run_checks(client: httpx.Client, speech_path: Path) -> Report:
    """Run the three checks against ``client`` (whose base URL is the server).

    Writes the speech file to ``speech_path``.

    Raises:
        CheckFailed: a check did not pass (the message says which and why).
        httpx.HTTPError: the server could not be reached.
    """
    health = _json(client.get("/v1/health"), "health check")
    if health.get("status") != "ok" or health.get("model") != MODEL_ID:
        raise CheckFailed(f"health check: unexpected answer {health}")

    speech = client.post(
        "/v1/audio/speech",
        json={"input": SPEECH_TEXT, "voice": VOICE, "response_format": "mp3"},
    )
    if speech.status_code != 200:
        raise CheckFailed(f"speech: HTTP {speech.status_code}: {speech.text[:300]}")
    audio = speech.content
    is_mp3 = audio[:3] == b"ID3" or (len(audio) > 1 and audio[0] == 0xFF and audio[1] >= 0xE0)
    if not is_mp3:
        raise CheckFailed("speech: the answer is not an MP3 file")
    speech_path.parent.mkdir(parents=True, exist_ok=True)
    speech_path.write_bytes(audio)

    timed = _json(
        client.post("/v1/tts/timestamps", json={"text": TIMESTAMP_TEXT, "voice": VOICE}),
        "word timestamps",
    )
    words = [str(w.get("text")) for w in timed.get("words", [])]
    if words != TIMESTAMP_WORDS:
        raise CheckFailed(f"word timestamps: expected words {TIMESTAMP_WORDS}, got {words}")
    starts = [int(w["start_ms"]) for w in timed["words"]]
    duration = int(timed.get("duration_ms", 0))
    if starts != sorted(starts) or duration <= 0:
        raise CheckFailed("word timestamps: timings are not in order")

    return Report(
        version=str(health.get("version", "?")),
        voices=int(health.get("voices", 0)),
        builder=str(health.get("builder", "none")),
        speech_path=speech_path,
        speech_bytes=len(audio),
        words=words,
        duration_ms=duration,
    )


def check(base_url: str, api_key: str | None, speech_path: Path) -> int:
    """Run the smoke test against ``base_url``, print the result, return the exit status."""
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    print(f"Checking the Supertonic server at {base_url}", flush=True)
    try:
        with httpx.Client(
            base_url=base_url.rstrip("/"), headers=headers, timeout=TIMEOUT_S, trust_env=False
        ) as client:
            report = run_checks(client, speech_path)
    except httpx.HTTPError as exc:
        print(f"FAIL: could not reach the server at {base_url} ({exc.__class__.__name__}).")
        print("Is it running? Start it with `uv run supertonic-server serve`, or pass --url.")
        return 1
    except CheckFailed as exc:
        print(f"FAIL: {exc}")
        return 1
    print(f"ok  health: version {report.version}, {report.voices} voices, builder {report.builder}")
    print(f"ok  speech: {report.speech_bytes} bytes of MP3 written to {report.speech_path}")
    print(f"ok  word timestamps: {' / '.join(report.words)} ({report.duration_ms} ms of audio)")
    print("PASS")
    return 0
