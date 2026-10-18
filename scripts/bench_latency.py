"""Measure time-to-first-audio (TTFA) for N concurrent realtime sessions.

Engine mode loads the model in-process; each session repeatedly synthesises one first
sentence at realtime priority. WebSocket mode is completed in Task 9.
"""

from __future__ import annotations

import argparse
import asyncio
import statistics
import sys
import time

from supertonic_server.core.config import Settings
from supertonic_server.engine import PRIORITY_REALTIME, Engine, load_engine
from supertonic_server.voices import VoiceLibrary

SENTENCE = "Hi, thanks for joining the meeting today."


def percentile(values: list[float], q: float) -> float:
    """Return the ``q`` quantile (0-1) of ``values`` by nearest rank."""
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(q * len(ordered)))]


async def run_session(
    engine: Engine, library: VoiceLibrary, args: argparse.Namespace
) -> tuple[list[float], float]:
    """Run one session; return its TTFAs in ms and the audio seconds it produced."""
    style = library.style(args.voice)
    ttfa: list[float] = []
    audio_s = 0.0
    for i in range(args.warmup + args.rounds):
        start = time.perf_counter()
        audio = await engine.synth(SENTENCE, style, "en", 1.05, args.steps, PRIORITY_REALTIME)
        elapsed = (time.perf_counter() - start) * 1000
        if i >= args.warmup:
            ttfa.append(elapsed)
            audio_s += len(audio) / engine.sample_rate
    return ttfa, audio_s


async def bench_engine(args: argparse.Namespace) -> int:
    """Benchmark the in-process engine and print the summary."""
    settings = Settings(workers=args.workers, intra_op_threads=args.threads)
    engine, presets = load_engine(settings)
    library = VoiceLibrary(presets, settings.custom_voices_dir)
    print(
        f"workers={settings.effective_workers()} intra_op_threads={args.threads} "
        f"steps={args.steps} sessions={args.sessions} rounds={args.rounds}"
    )
    start = time.perf_counter()
    results = await asyncio.gather(
        *(run_session(engine, library, args) for _ in range(args.sessions))
    )
    wall = time.perf_counter() - start
    samples = [t for ttfa, _ in results for t in ttfa]
    audio_s = sum(a for _, a in results)
    print(
        f"ttfa_ms p50={statistics.median(samples):.0f} p95={percentile(samples, 0.95):.0f} "
        f"max={max(samples):.0f}"
    )
    print(f"real_time_factor={audio_s / wall:.1f}x (audio s / wall s, incl. warm-up wall time)")
    return 0


def main() -> int:
    """Parse arguments and run the selected benchmark mode."""
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--mode", choices=["engine", "ws"], default="engine")
    p.add_argument("--sessions", type=int, default=1)
    p.add_argument("--url", default="ws://127.0.0.1:8787/v1/realtime")
    p.add_argument("--api-key", default=None)
    p.add_argument("--workers", type=int, default=0)
    p.add_argument("--threads", type=int, default=None, help="intra-op threads per worker")
    p.add_argument("--steps", type=int, default=8)
    p.add_argument("--voice", default="F1")
    p.add_argument("--rounds", type=int, default=10)
    p.add_argument("--warmup", type=int, default=2)
    args = p.parse_args()
    if args.mode == "ws":
        print("ws mode: not implemented until Task 9", file=sys.stderr)
        return 2
    return asyncio.run(bench_engine(args))


if __name__ == "__main__":
    sys.exit(main())
