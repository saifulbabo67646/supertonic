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

## Findings

- Cost is almost linear in denoising steps (about 65 ms per step per sentence); the default
  8 steps cannot meet the realtime targets on this machine.
- 4 workers with 3 intra-op threads each avoids oversubscription at 4 sessions.
- The best setting that meets both targets with the highest quality is **4 steps, 4 workers,
  3 intra-op threads**. The 4-session p95 (598 ms) is right at the limit.
- `Settings.realtime_steps` (`SUPERTONIC_REALTIME_STEPS`, default 4) holds this value. The
  engine does not apply it by itself; realtime routes pass it for `PRIORITY_REALTIME` calls.
- Audio quality at 3-4 steps has not been evaluated; compare by ear before relying on it.
- Recommended for realtime use: `SUPERTONIC_WORKERS=4 SUPERTONIC_INTRA_OP_THREADS=3`.
