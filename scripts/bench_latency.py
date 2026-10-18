"""Measure time-to-first-audio (TTFA) for N concurrent realtime sessions.

Engine mode loads the model in-process; each session repeatedly synthesises one first
sentence at realtime priority. TTFA is approximated by the ``Engine.synth`` latency of that
single sentence (the whole sentence, not a streamed first packet). Sessions fire in lockstep,
which is the worst case for queueing. Real-time factor covers measured rounds only.

WebSocket mode connects N sockets to a running server; each round every socket sends
``input_text_buffer.append`` (the sentence plus a space, so it is complete) and
``input_text_buffer.commit``, and TTFA is the time from sending the append to receiving the
first ``audio_output.delta``. Rounds start in lockstep across sockets. The server applies
``SUPERTONIC_REALTIME_STEPS``; ``--steps`` only affects engine mode.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from typing import Any

from supertonic_server.core.config import Settings
from supertonic_server.engine import PRIORITY_REALTIME, Engine, load_engine
from supertonic_server.voices import VoiceLibrary

SENTENCE = "Hi, thanks for joining the meeting today."


def percentile(values: list[float], q: float) -> float:
    """Return the ``q`` quantile (0-1) of ``values`` by nearest rank."""
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(q * len(ordered)))]


async def run_session(
    engine: Engine, library: VoiceLibrary, args: argparse.Namespace, rounds: int
) -> tuple[list[float], float]:
    """Run ``rounds`` rounds; return each round's TTFA in ms and the audio seconds produced."""
    style = library.style(args.voice)
    ttfa: list[float] = []
    audio_s = 0.0
    for _ in range(rounds):
        start = time.perf_counter()
        audio = await engine.synth(SENTENCE, style, "en", 1.05, args.steps, PRIORITY_REALTIME)
        ttfa.append((time.perf_counter() - start) * 1000)
        audio_s += len(audio) / engine.sample_rate
    return ttfa, audio_s


async def bench_engine(args: argparse.Namespace) -> int:
    """Benchmark the in-process engine and print the summary."""
    settings = Settings(workers=args.workers, intra_op_threads=args.threads)
    engine, presets = load_engine(settings)
    library = VoiceLibrary(presets, settings.custom_voices_dir)
    print(
        f"workers={settings.effective_workers()} "
        f"intra_op_threads={settings.effective_intra_op_threads()} "
        f"steps={args.steps} sessions={args.sessions} rounds={args.rounds}"
    )
    await asyncio.gather(
        *(run_session(engine, library, args, args.warmup) for _ in range(args.sessions))
    )
    start = time.perf_counter()
    results = await asyncio.gather(
        *(run_session(engine, library, args, args.rounds) for _ in range(args.sessions))
    )
    wall = time.perf_counter() - start
    samples = [t for ttfa, _ in results for t in ttfa]
    audio_s = sum(a for _, a in results)
    print(
        f"ttfa_ms p50={statistics.median(samples):.0f} p95={percentile(samples, 0.95):.0f} "
        f"max={max(samples):.0f}"
    )
    print(f"real_time_factor={audio_s / wall:.1f}x (audio s / wall s, measured rounds)")
    return 0


async def ws_session(
    args: argparse.Namespace, barrier: asyncio.Barrier, rounds: int
) -> list[float]:
    """Open one socket and return the append-to-first-delta latency (ms) of each round."""
    from websockets.asyncio.client import connect

    headers = {"Authorization": f"Bearer {args.api_key}"} if args.api_key else None
    url = f"{args.url}?voice={args.voice}"
    ttfa: list[float] = []
    async with connect(url, additional_headers=headers, max_size=None) as sock:

        async def recv() -> dict[str, Any]:
            event: dict[str, Any] = json.loads(await sock.recv())
            if event["type"] == "conversation.item.tts.failed":
                raise RuntimeError(f"server error: {event['error']}")
            return event

        assert (await recv())["type"] == "session.created"
        for _ in range(rounds):
            await barrier.wait()
            start = time.perf_counter()
            await sock.send(
                json.dumps({"type": "input_text_buffer.append", "text": SENTENCE + " "})
            )
            await sock.send(json.dumps({"type": "input_text_buffer.commit"}))
            while (await recv())["type"] != "conversation.item.audio_output.delta":
                pass
            ttfa.append((time.perf_counter() - start) * 1000)
            while (await recv())["type"] != "conversation.item.audio_output.done":
                pass
    return ttfa


async def bench_ws(args: argparse.Namespace) -> int:
    """Benchmark a running server's realtime WebSocket and print the summary."""
    print(f"url={args.url} sessions={args.sessions} warmup={args.warmup} rounds={args.rounds}")
    barrier = asyncio.Barrier(args.sessions)
    total = args.warmup + args.rounds
    results = await asyncio.gather(
        *(ws_session(args, barrier, total) for _ in range(args.sessions))
    )
    samples = [t for r in results for t in r[args.warmup :]]
    print(
        f"ttfa_ms p50={statistics.median(samples):.0f} p95={percentile(samples, 0.95):.0f} "
        f"max={max(samples):.0f}"
    )
    return 0


def main() -> int:
    """Parse arguments and run the selected benchmark mode."""
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--mode", choices=["engine", "ws"], default="engine")
    p.add_argument("--sessions", type=int, default=1)
    p.add_argument("--url", default="ws://127.0.0.1:8787/v1/audio/speech/websocket")
    p.add_argument("--api-key", default=None)
    p.add_argument("--workers", type=int, default=0)
    p.add_argument("--threads", type=int, default=None, help="intra-op threads per worker")
    p.add_argument("--steps", type=int, default=8)
    p.add_argument("--voice", default="F1")
    p.add_argument("--rounds", type=int, default=10)
    p.add_argument("--warmup", type=int, default=2)
    args = p.parse_args()
    if args.mode == "ws":
        return asyncio.run(bench_ws(args))
    return asyncio.run(bench_engine(args))


if __name__ == "__main__":
    sys.exit(main())
