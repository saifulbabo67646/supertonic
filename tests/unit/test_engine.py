"""Tests for the priority scheduler and the sentence-streaming engine."""

from __future__ import annotations

import asyncio
import gc
import logging
import threading
import time
import weakref
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from supertonic.config import DEFAULT_SILENCE_DURATION
from supertonic.core import Style

from fakes import FakeModel, fake_style
from supertonic_server.core.config import Settings
from supertonic_server.core.errors import ApiError
from supertonic_server.engine import (
    PRIORITY_DEFAULT,
    PRIORITY_REALTIME,
    Chunk,
    Engine,
    Scheduler,
    ServerBusy,
    load_engine,
)


async def test_stream_order_and_trim(engine: Engine, style: Style) -> None:
    chunks = [c async for c in engine.stream("One. Two two. Three.", style, "en")]
    assert [c.text for c in chunks] == ["One.", "Two two.", "Three."]
    assert all(c.audio.dtype == np.float32 and c.audio.ndim == 1 for c in chunks)
    # Trimmed to the reported duration: the fake pads every output with extra samples.
    assert len(chunks[1].audio) == int(0.05 * len("Two two.") / 1.05 * 44100)


async def test_stream_passes_parameters(style: Style) -> None:
    model = FakeModel()
    eng = Engine(model, Scheduler(workers=1, max_queue=8))
    [c async for c in eng.stream("Hola.", style, "es", speed=1.5, steps=12)]
    assert model.calls[0][0] == ["Hola."] and model.calls[0][2:] == (12, 1.5, "es")


async def test_empty_after_sanitize(engine: Engine, style: Style) -> None:
    with pytest.raises(ApiError) as e:
        [c async for c in engine.stream("😀 ★", style, "en")]
    assert e.value.code == "empty_input" and e.value.param == "input"


def test_prepare_drops_unsupported_and_limits_length(engine: Engine) -> None:
    assert engine.prepare("Hi 😀 there. Bye★.", "en") == ["Hi there.", "Bye ."]
    with pytest.raises(ApiError) as e:
        engine.prepare("a" * 100_001, "en")
    assert e.value.status == 400 and e.value.code == "input_too_long"


async def test_speed_validation(engine: Engine, style: Style) -> None:
    with pytest.raises(ApiError) as e:
        await engine.synth("Hi.", style, "en", 2.5, 8, PRIORITY_DEFAULT)
    assert e.value.code == "invalid_speed" and e.value.param == "speed"


@pytest.mark.parametrize("steps", [0, 101])
async def test_steps_validation(engine: Engine, style: Style, steps: int) -> None:
    with pytest.raises(ApiError) as e:
        await engine.synth("Hi.", style, "en", 1.0, steps, PRIORITY_DEFAULT)
    assert e.value.code == "invalid_total_steps"


async def test_stream_validates_before_work(style: Style) -> None:
    model = FakeModel()
    eng = Engine(model, Scheduler(workers=1, max_queue=8))
    with pytest.raises(ApiError) as e:
        [c async for c in eng.stream("Hi.", style, "en", speed=0.5)]
    assert e.value.code == "invalid_speed" and model.calls == []


async def test_render_joins_with_silence(engine: Engine, style: Style) -> None:
    audio, chunks = await engine.render("One. Two.", style, "en")
    gap = int(DEFAULT_SILENCE_DURATION * 44100)
    assert [c.text for c in chunks] == ["One.", "Two."]
    assert len(audio) == len(chunks[0].audio) + gap + len(chunks[1].audio)
    start = len(chunks[0].audio)
    assert not audio[start : start + gap].any() and audio.dtype == np.float32
    assert isinstance(chunks[0], Chunk)


async def test_realtime_priority_jumps_queue() -> None:
    model = FakeModel(delay=0.05)
    eng = Engine(model, Scheduler(workers=1, max_queue=64))
    st = fake_style()
    batch = [
        asyncio.create_task(eng.synth(f"bulk {i}.", st, "en", 1.05, 8, PRIORITY_DEFAULT))
        for i in range(5)
    ]
    await asyncio.sleep(0.01)
    rt = asyncio.create_task(eng.synth("live.", st, "en", 1.05, 8, PRIORITY_REALTIME))
    await asyncio.gather(rt, *batch)
    order = [c[0][0] for c in model.calls]
    assert order.index("live.") <= 1  # at most the job already running goes first


async def test_fifo_within_priority() -> None:
    model = FakeModel(delay=0.01)
    eng = Engine(model, Scheduler(workers=1, max_queue=64))
    st = fake_style()
    await asyncio.gather(*(eng.synth(f"s{i}.", st, "en", 1.05, 8, 10) for i in range(6)))
    assert [c[0][0] for c in model.calls] == [f"s{i}." for i in range(6)]


async def test_queue_full_raises_busy() -> None:
    eng = Engine(FakeModel(delay=0.2), Scheduler(workers=1, max_queue=2))
    st = fake_style()
    tasks = [asyncio.create_task(eng.synth(f"x{i}.", st, "en", 1.05, 8, 10)) for i in range(3)]
    await asyncio.sleep(0.01)
    with pytest.raises(ServerBusy) as e:
        await eng.synth("over.", st, "en", 1.05, 8, 10)
    assert e.value.status == 503 and e.value.code == "server_busy"
    assert e.value.type == "server_error"
    await asyncio.gather(*tasks)


async def test_workers_run_in_parallel() -> None:
    sched = Scheduler(workers=2, max_queue=8)
    barrier = threading.Barrier(2, timeout=5)
    # Each job blocks until the other is running too; serial execution would break the barrier.
    results = await asyncio.gather(*(sched.submit(barrier.wait, 10) for _ in range(2)))
    assert sorted(results) == [0, 1]
    sched.close()


async def test_cancelled_waiter_never_runs() -> None:
    sched = Scheduler(workers=1, max_queue=8)
    ran: list[str] = []

    def job(name: str, delay: float) -> str:
        time.sleep(delay)
        ran.append(name)
        return name

    first = asyncio.create_task(sched.submit(lambda: job("first", 0.05), 10))
    second = asyncio.create_task(sched.submit(lambda: job("second", 0.0), 10))
    third = asyncio.create_task(sched.submit(lambda: job("third", 0.0), 10))
    await asyncio.sleep(0.01)
    second.cancel()
    assert await first == "first" and await third == "third"
    with pytest.raises(asyncio.CancelledError):
        await second
    assert ran == ["first", "third"]


async def test_cancelled_running_job_result_discarded() -> None:
    sched = Scheduler(workers=1, max_queue=8)
    done: list[int] = []

    def boom() -> None:
        time.sleep(0.05)
        done.append(1)
        raise RuntimeError("discarded")

    task = asyncio.create_task(sched.submit(boom, 10))
    await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    # The worker is freed once the thread finishes and later jobs still run.
    assert await sched.submit(lambda: 42, 10) == 42 and done == [1]


async def test_job_exception_propagates() -> None:
    sched = Scheduler(workers=1, max_queue=8)

    def bad() -> None:
        raise ValueError("nope")

    with pytest.raises(ValueError, match="nope"):
        await sched.submit(bad, 10)


async def test_closed_scheduler_rejects_and_cancels_waiting() -> None:
    sched = Scheduler(workers=1, max_queue=8)
    running = asyncio.create_task(sched.submit(lambda: time.sleep(0.05), 10))
    waiting = asyncio.create_task(sched.submit(lambda: None, 10))
    await asyncio.sleep(0.01)
    sched.close()
    with pytest.raises(ServerBusy):
        await waiting
    await running
    with pytest.raises(ServerBusy):
        await sched.submit(lambda: None, 10)


async def test_abandoned_stream_drops_queued_work(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.ERROR)
    model = FakeModel(delay=0.05)
    eng = Engine(model, Scheduler(workers=1, max_queue=64))
    gen = eng.stream("A. B. C. D. E. F.", fake_style(), "en")
    await gen.__anext__()
    await gen.aclose()
    await asyncio.sleep(0.3)
    # The first sentence plus its lookahead (already running when the stream closed).
    assert [c[0][0] for c in model.calls] == ["A.", "B."]
    assert eng.scheduler.waiting == 0 and eng.scheduler.running == 0
    assert [r for r in caplog.records if r.levelno >= logging.ERROR] == []


async def test_cancelled_stream_consumer_drops_work() -> None:
    model = FakeModel(delay=0.1)
    eng = Engine(model, Scheduler(workers=1, max_queue=64))

    async def consume() -> None:
        async for _ in eng.stream("A. B. C. D. E. F.", fake_style(), "en"):
            pass

    task = asyncio.create_task(consume())
    await asyncio.sleep(0.15)  # "A." done, "B." running, "C." queued
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await asyncio.sleep(0.2)
    assert [c[0][0] for c in model.calls] == ["A.", "B."]
    assert eng.scheduler.waiting == 0 and eng.scheduler.running == 0


async def test_stream_lookahead_is_one_sentence() -> None:
    model = FakeModel(delay=0.02)
    eng = Engine(model, Scheduler(workers=4, max_queue=64))
    gen = eng.stream("A. B. C. D. E. F.", fake_style(), "en")
    await gen.__anext__()
    await asyncio.sleep(0.1)
    assert [c[0][0] for c in model.calls] == ["A.", "B."]
    await gen.aclose()


async def test_stream_does_not_retain_consumed_audio() -> None:
    eng = Engine(FakeModel(), Scheduler(workers=1, max_queue=64))
    gen = eng.stream("A. B. C. D. E. F.", fake_style(), "en")
    first = await gen.__anext__()
    ref = weakref.ref(first.audio)
    del first
    await gen.__anext__()
    await gen.__anext__()
    gc.collect()
    assert ref() is None  # the engine kept no reference to audio the consumer dropped
    await gen.aclose()


def test_load_engine_builds_tts(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import supertonic

    seen: dict[str, Any] = {}

    class FakeTTS:
        def __init__(self, **kwargs: Any) -> None:
            seen.update(kwargs)
            self.model = FakeModel()
            self.model_dir = tmp_path

    monkeypatch.setattr(supertonic, "TTS", FakeTTS)
    eng, presets = load_engine(Settings(model_dir=tmp_path, intra_op_threads=3))
    assert isinstance(eng, Engine) and presets == tmp_path / "voice_styles"
    assert seen == {
        "model": "supertonic-3",
        "model_dir": tmp_path,
        "auto_download": True,
        "intra_op_num_threads": 3,
    }
    eng.scheduler.close()
