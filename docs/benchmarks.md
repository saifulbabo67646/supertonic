# Latency benchmarks

Time to first audio (TTFA) = time for the first sentence (`"Hi, thanks for joining the
meeting today."`, `en`, voice F1, speed 1.05) to be synthesised at realtime priority.
Each session runs 2 warm-up + 10 measured rounds; N sessions run concurrently.

Reproduce: `uv run python scripts/bench_latency.py --sessions N --workers W --threads T --steps S`

**Machine:** Apple M4, 10 cores, macOS, CPU ONNX Runtime, supertonic 1.3.1.
**Targets:** < 300 ms alone, < 600 ms with 4 concurrent sessions.

| workers | intra-op threads | steps | 1 session p50 / p95 (ms) | 4 sessions p50 / p95 (ms) |
|---|---|---|---|---|
| 5 (default) | default | 8 | 774 / 923 | 1368 / 1560 |
| 2 | 4 | 8 | 719 / 843 | 1600 / 1839 |
| 2 | 4 | 5 | 339 / 351 | 941 / 1043 |
| 4 | 2 | 5 | 334 / 343 | 674 / 724 |
| 4 | 3 | 5 | 328 / 330 | 642 / 720 |
| 3 | 3 | 5 | 327 / 328 | 644 / 985 |
| **4** | **3** | **4** | **266 / 270** | **521 / 598** |
| 4 | 2 | 4 | 272 / 287 | 542 / 595 |
| 4 | 3 | 3 | 207 / 212 | 399 / 478 |
| 2 | 4 | 3 | 216 / 306 | 580 / 615 |

## Repeatability (new defaults: 4 workers x 3 threads, 30 measured rounds, 3 runs each)

Defaults now resolve to `min(4, max(1, cpu_count // 2))` workers and
`ceil(cpu_count / workers)` intra-op threads (M4: 4 x 3). TTFA in ms.

| steps | sessions | p50 per run | p95 per run | max per run |
|---|---|---|---|---|
| 4 | 1 | 267 / 267 / 267 | 271 / 271 / 273 | 280 / 273 / 277 |
| 4 | 4 | 522 / 523 / 531 | 590 / 588 / **607** | 607 / 612 / 620 |
| 3 | 1 | 209 / 208 / 208 | 212 / 211 / 212 | 219 / 237 / 212 |
| 3 | 4 | 407 / 407 / 405 | 464 / 468 / 471 | 486 / 497 / 493 |

4 steps exceeds 600 ms p95 in one of three 4-session runs, so `realtime_steps` defaults to
**3** (4-session p95 at most 471 ms, 1-session p95 about 212 ms). Real-time factor at 3 steps
is about 13x alone and 27x with 4 sessions.

## Findings

- Cost is almost linear in denoising steps (about 65 ms per step per sentence); the default
  8 steps cannot meet the realtime targets on this machine.
- 4 workers with 3 intra-op threads each avoids oversubscription at 4 sessions.
- `Settings.realtime_steps` (`SUPERTONIC_REALTIME_STEPS`, default 3) holds the step count for
  realtime use. The engine does not apply it by itself; realtime routes will pass it for
  `PRIORITY_REALTIME` calls (planned, Task 9).
- Audio quality at 3-4 steps has not been evaluated; compare by ear before relying on it.
- The table above the repeatability section was measured with the earlier harness (warm-up
  time included in the real-time factor; thread counts set explicitly).
