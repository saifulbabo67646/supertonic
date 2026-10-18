"""JobManager: single-slot queue, worker process lifecycle, persistence and voice import."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import threading
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from fakes_builder import FAKE_WORKER
from supertonic_server.builder import (
    BuildRequest,
    Job,
    PreparedAudio,
    availability,
    jobs,
    runlog,
)
from supertonic_server.builder.availability import ProbeResult, detect_local_builder
from supertonic_server.builder.jobs import JobManager
from supertonic_server.core.errors import ApiError
from supertonic_server.voices import VoiceLibrary

FILES = [("ref.wav", b"fake-audio")]
TERMINAL = {"succeeded", "failed", "cancelled"}

ManagerFactory = Callable[..., Awaitable[JobManager]]


def _req(name: str = "Narrator", **kw: Any) -> BuildRequest:
    base: dict[str, Any] = {
        "name": name,
        "description": "a test voice",
        "tags": ["test"],
        "source_note": "my own recording",
        "consent": True,
    }
    return BuildRequest(**{**base, **kw})


def _fake_prepare(files: Sequence[tuple[str, bytes]], out_path: Path) -> PreparedAudio:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(b"RIFF-fake")
    return PreparedAudio(out_path, 5.0, 4.0, [n for n, _ in files])


def _alive(pid: int) -> bool:
    if sys.platform == "win32":
        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
            return code.value == 259  # STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    try:  # a zombie still answers kill(0); it is dead for our purposes
        waited, _ = os.waitpid(pid, os.WNOHANG)
    except ChildProcessError:
        return True
    return waited == 0


async def _until(pred: Callable[[], bool], within: float = 10.0) -> None:
    deadline = time.monotonic() + within
    while not pred():
        if time.monotonic() > deadline:
            raise AssertionError("condition not met in time")
        await asyncio.sleep(0.01)


async def _settled(mgr: JobManager, job_id: str, within: float = 10.0) -> Job:
    await _until(lambda: mgr.get(job_id).state in TERMINAL, within)
    return mgr.get(job_id)


def _run_info(control: Path, n: int = 0) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((control / f"run-{n}.json").read_text(encoding="utf-8"))
    return data


@pytest.fixture
def control(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "control"
    path.mkdir()
    monkeypatch.setenv("FAKE_BUILDER_DIR", str(path))
    return path


@pytest.fixture
def modes(monkeypatch: pytest.MonkeyPatch) -> Callable[..., None]:
    return lambda *m: monkeypatch.setenv("FAKE_BUILDER_MODES", ",".join(m))


@pytest.fixture
async def make_manager(
    tmp_path: Path, lib: VoiceLibrary, control: Path, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[ManagerFactory]:
    monkeypatch.setattr(jobs, "prepare_reference", _fake_prepare)
    made: list[JobManager] = []

    async def factory(**kw: Any) -> JobManager:
        args: dict[str, Any] = {"timeout_s": 30.0, "worker_cmd": [sys.executable, FAKE_WORKER]}
        mgr = JobManager(tmp_path / "data", lib, tmp_path / "models", **{**args, **kw})
        await mgr.start()
        made.append(mgr)
        return mgr

    yield factory
    for mgr in made:
        await mgr.close()


async def test_success_imports_voice_with_build_metadata(
    make_manager: ManagerFactory, lib: VoiceLibrary, control: Path, tmp_path: Path
) -> None:
    mgr = await make_manager()
    job = await mgr.submit(_req(method="fast"), FILES)
    assert job.state == "queued" and job.builder == "local"
    done = await _settled(mgr, job.id)
    assert done.state == "succeeded", done.error
    assert done.voice_id == "narrator" and done.started_at and done.finished_at
    assert done.progress is not None and done.progress.stage == "timbre"
    voice = lib.get("narrator")
    assert voice.description == "a test voice" and voice.tags == ["test"]
    assert voice.source_note == "my own recording"
    assert voice.build is not None
    assert voice.build["method"] == "fast" and voice.build["builder"] == "local"
    assert voice.build["stopped_early"] is False and voice.build["seconds"] >= 0
    assert voice.to_dict()["build"] == voice.build
    argv = _run_info(control)["argv"]
    assert argv[argv.index("--method") + 1] == "fast"
    job_dir = tmp_path / "data" / "jobs" / job.id
    assert argv[argv.index("--stop-file") + 1] == str(job_dir / "STOP")
    assert argv[argv.index("--model-dir") + 1] == str(tmp_path / "models")
    saved = json.loads((job_dir / "job.json").read_text(encoding="utf-8"))
    assert saved["state"] == "succeeded" and saved["voice_id"] == "narrator"
    lines = (job_dir / "progress.jsonl").read_text(encoding="utf-8").splitlines()
    assert [json.loads(line)["stage"] for line in lines] == ["loading", "timbre"]
    assert not (job_dir / "reference.wav").exists()


async def test_method_passed_through_and_label(
    make_manager: ManagerFactory, lib: VoiceLibrary, control: Path
) -> None:
    mgr = await make_manager()
    job = await mgr.submit(_req(), FILES, builder_label="remote:mac")
    done = await _settled(mgr, job.id)
    assert done.builder == "remote:mac"
    argv = _run_info(control)["argv"]
    assert argv[argv.index("--method") + 1] == "accurate"
    build = lib.get(done.voice_id or "").build
    assert build is not None and build["builder"] == "remote:mac"


async def test_non_json_stdout_is_logged_not_fatal(
    make_manager: ManagerFactory, modes: Callable[..., None], tmp_path: Path
) -> None:
    modes("noisy")
    mgr = await make_manager()
    done = await _settled(mgr, (await mgr.submit(_req(), FILES)).id)
    assert done.state == "succeeded"
    log = (tmp_path / "data" / "jobs" / done.id / "worker.log").read_text(encoding="utf-8")
    assert "this is not json" in log


async def test_method_unavailable(make_manager: ManagerFactory) -> None:
    mgr = await make_manager(methods=("fast",))
    assert mgr.methods == ("fast",)
    with pytest.raises(ApiError) as exc:
        await mgr.submit(_req(method="accurate"), FILES)
    assert exc.value.status == 400 and exc.value.code == "method_unavailable"
    assert exc.value.param == "method" and mgr.list() == []


async def test_invalid_request_and_audio_leave_no_job(
    make_manager: ManagerFactory, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    mgr = await make_manager()
    with pytest.raises(ApiError) as exc:
        await mgr.submit(_req(consent=False), FILES)
    assert exc.value.code == "consent_required"
    from supertonic_server.builder import audio_prep

    monkeypatch.setattr(jobs, "prepare_reference", audio_prep.prepare_reference)
    with pytest.raises(ApiError) as exc:
        await mgr.submit(_req(), [("x.wav", b"not audio at all")])
    assert exc.value.code == "invalid_reference_audio"
    assert mgr.list() == []
    assert list((tmp_path / "data" / "jobs").iterdir()) == []


async def test_crash_fails_with_stderr_line_and_next_job_runs(
    make_manager: ManagerFactory, modes: Callable[..., None], tmp_path: Path
) -> None:
    modes("crash", "ok")
    mgr = await make_manager()
    first = await mgr.submit(_req(), FILES)
    second = await mgr.submit(_req("Second"), FILES)
    failed = await _settled(mgr, first.id)
    assert failed.state == "failed" and failed.voice_id is None
    assert failed.error == {"code": "worker_failed", "message": "RuntimeError: kaboom"}
    log = (tmp_path / "data" / "jobs" / first.id / "worker.log").read_text(encoding="utf-8")
    assert "RuntimeError: kaboom" in log
    assert (await _settled(mgr, second.id)).state == "succeeded"


async def test_error_event_out_of_memory(
    make_manager: ManagerFactory, modes: Callable[..., None], lib: VoiceLibrary
) -> None:
    modes("error:out_of_memory")
    mgr = await make_manager()
    done = await _settled(mgr, (await mgr.submit(_req(), FILES)).id)
    assert done.state == "failed"
    assert done.error is not None and done.error["code"] == "out_of_memory"
    assert [v for v in lib.list() if v.kind == "custom"] == []


async def test_timeout_kills_tree(
    make_manager: ManagerFactory, modes: Callable[..., None], control: Path
) -> None:
    modes("hang")
    mgr = await make_manager(timeout_s=1.0)
    done = await _settled(mgr, (await mgr.submit(_req(), FILES)).id)
    assert done.state == "failed"
    assert done.error is not None and done.error["code"] == "timeout"
    info = _run_info(control)
    await _until(lambda: not _alive(info["pid"]) and not _alive(info["child_pid"]), 5)


@pytest.mark.parametrize("mode", ["hang", "gate"])  # during "model load" / "optimisation"
async def test_cancel_running_kills_tree_and_imports_nothing(
    make_manager: ManagerFactory,
    modes: Callable[..., None],
    control: Path,
    lib: VoiceLibrary,
    tmp_path: Path,
    mode: str,
) -> None:
    modes(mode)
    mgr = await make_manager()
    job = await mgr.submit(_req(), FILES)
    await _until(lambda: (control / "run-0.json").exists())
    await _until(lambda: mgr.get(job.id).state == "running")
    if mode == "gate":  # optimising: at least one timbre step reported before the cancel
        await _until(lambda: (p := mgr.get(job.id).progress) is not None and p.stage == "timbre")
    info = _run_info(control)
    t0 = time.monotonic()
    cancelled = await mgr.cancel(job.id)
    assert cancelled.state == "cancelled" and time.monotonic() - t0 < 5
    assert cancelled.voice_id is None and cancelled.finished_at
    pids = [p for p in (info["pid"], info["child_pid"]) if p]
    await _until(lambda: not any(_alive(p) for p in pids), 5)
    (control / "go").touch()  # a surviving gate worker would now finish and import
    await asyncio.sleep(0.2)
    assert [v for v in lib.list() if v.kind == "custom"] == []
    job_dir = tmp_path / "data" / "jobs" / job.id
    assert sorted(p.name for p in job_dir.iterdir() if p.name != "progress.jsonl") == [
        "job.json",
        "worker.log",
    ]
    assert json.loads((job_dir / "job.json").read_text(encoding="utf-8"))["state"] == "cancelled"
    assert (await mgr.cancel(job.id)).state == "cancelled"  # idempotent


async def test_cancel_queued_and_finished(
    make_manager: ManagerFactory, modes: Callable[..., None], control: Path
) -> None:
    modes("gate", "ok")
    mgr = await make_manager()
    first = await mgr.submit(_req(), FILES)
    await _until(lambda: (control / "run-0.json").exists())
    second = await mgr.submit(_req("Second"), FILES)
    assert (await mgr.cancel(second.id)).state == "cancelled"
    (control / "go").touch()
    done = await _settled(mgr, first.id)
    assert done.state == "succeeded"
    assert (await mgr.cancel(first.id)).state == "succeeded"
    assert not (control / "run-1.json").exists()  # the cancelled job never started


async def test_finish_running_stops_early(
    make_manager: ManagerFactory, modes: Callable[..., None], control: Path, lib: VoiceLibrary
) -> None:
    modes("gate")
    mgr = await make_manager()
    job = await mgr.submit(_req(), FILES)
    await _until(lambda: (control / "run-0.json").exists())
    await _until(lambda: mgr.get(job.id).state == "running")
    stopping = await mgr.finish(job.id)
    assert stopping.stopping is True
    done = await _settled(mgr, job.id)
    assert done.state == "succeeded"
    build = lib.get(done.voice_id or "").build
    assert build is not None and build["stopped_early"] is True
    assert (await mgr.finish(job.id)).state == "succeeded"  # finished: unchanged


async def test_finish_queued_is_not_running(
    make_manager: ManagerFactory, modes: Callable[..., None], control: Path
) -> None:
    modes("gate", "ok")
    mgr = await make_manager()
    first = await mgr.submit(_req(), FILES)
    await _until(lambda: (control / "run-0.json").exists())
    second = await mgr.submit(_req("Second"), FILES)
    with pytest.raises(ApiError) as exc:
        await mgr.finish(second.id)
    assert exc.value.status == 409 and exc.value.code == "job_not_running"
    (control / "go").touch()
    assert (await _settled(mgr, first.id)).state == "succeeded"
    assert (await _settled(mgr, second.id)).state == "succeeded"


async def test_single_slot(
    make_manager: ManagerFactory, modes: Callable[..., None], control: Path
) -> None:
    modes("gate", "ok")
    mgr = await make_manager()
    first = await mgr.submit(_req(), FILES)
    second = await mgr.submit(_req("Second"), FILES)
    await _until(lambda: (control / "run-0.json").exists())
    await asyncio.sleep(0.2)
    assert mgr.get(first.id).state == "running" and mgr.get(second.id).state == "queued"
    assert not (control / "run-1.json").exists()
    (control / "go").touch()
    done1 = await _settled(mgr, first.id)
    done2 = await _settled(mgr, second.id)
    assert done1.finished_at and done2.started_at and done1.finished_at <= done2.started_at
    assert [j.id for j in mgr.list()] == [second.id, first.id]  # newest first
    assert [j.id for j in mgr.list(limit=1)] == [second.id]


async def test_ninth_waiting_job_is_busy(
    make_manager: ManagerFactory, modes: Callable[..., None], control: Path
) -> None:
    modes("gate", "ok")
    mgr = await make_manager()
    await mgr.submit(_req(), FILES)
    await _until(lambda: (control / "run-0.json").exists())
    for i in range(8):
        await mgr.submit(_req(f"Waiting {i}"), FILES)
    with pytest.raises(ApiError) as exc:
        await mgr.submit(_req("Too many"), FILES)
    assert exc.value.status == 503 and exc.value.code == "builder_busy"
    assert len(mgr.list()) == 9


async def test_concurrent_same_name_get_distinct_ids(
    make_manager: ManagerFactory, lib: VoiceLibrary
) -> None:
    mgr = await make_manager()
    a, b = await asyncio.gather(mgr.submit(_req(), FILES), mgr.submit(_req(), FILES))
    done = [await _settled(mgr, a.id), await _settled(mgr, b.id)]
    assert {j.state for j in done} == {"succeeded"}
    assert sorted(j.voice_id or "" for j in done) == ["narrator", "narrator-2"]
    assert {v.id for v in lib.list() if v.kind == "custom"} == {"narrator", "narrator-2"}


async def test_get_unknown_job(make_manager: ManagerFactory) -> None:
    mgr = await make_manager()
    for call in (mgr.cancel, mgr.finish):
        with pytest.raises(ApiError) as exc:
            await call("nope")
        assert exc.value.status == 404 and exc.value.code == "job_not_found"
    with pytest.raises(ApiError):
        mgr.get("nope")


def _write_job(root: Path, job_id: str, state: str, created: datetime) -> Path:
    job = Job(
        id=job_id,
        state=state,  # type: ignore[arg-type]
        request=_req(),
        created_at=created.isoformat(),
        started_at=None,
        finished_at=None,
        progress=None,
        voice_id=None,
        error=None,
        builder="local",
    )
    folder = root / job_id
    folder.mkdir(parents=True)
    (folder / "job.json").write_text(json.dumps(job.to_dict()), encoding="utf-8")
    (folder / "reference.wav").write_bytes(b"x")
    return folder


async def test_restart_recovery_and_prune(make_manager: ManagerFactory, tmp_path: Path) -> None:
    root = tmp_path / "data" / "jobs"
    now = datetime.now(UTC)
    _write_job(root, "running1", "running", now - timedelta(hours=1))
    _write_job(root, "queued1", "queued", now - timedelta(hours=2))
    _write_job(root, "recent", "succeeded", now - timedelta(days=6))
    old = _write_job(root, "old", "succeeded", now - timedelta(days=8))
    mgr = await make_manager()
    for job_id in ("running1", "queued1"):
        job = mgr.get(job_id)
        assert job.state == "failed" and job.finished_at
        assert job.error is not None and job.error["code"] == "interrupted"
        saved = json.loads((root / job_id / "job.json").read_text(encoding="utf-8"))
        assert saved["state"] == "failed"
        assert not (root / job_id / "reference.wav").exists()
    assert mgr.get("recent").state == "succeeded"
    assert not old.exists()
    with pytest.raises(ApiError):
        mgr.get("old")
    assert [j.id for j in mgr.list()] == ["running1", "queued1", "recent"]


async def test_close_cancels_running_job(
    make_manager: ManagerFactory, modes: Callable[..., None], control: Path
) -> None:
    modes("hang")
    mgr = await make_manager()
    job = await mgr.submit(_req(), FILES)
    await _until(lambda: (control / "run-0.json").exists())
    info = _run_info(control)
    await mgr.close()
    assert mgr.get(job.id).state == "cancelled"
    await _until(lambda: not _alive(info["pid"]) and not _alive(info["child_pid"]), 5)


async def test_real_worker_fake_extractor(
    tmp_path: Path, lib: VoiceLibrary, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The default command runs ``python -m supertonic_server.builder.worker``."""
    from test_audio_prep import _speech, _wav_bytes

    monkeypatch.setenv("SUPERTONIC_BUILDER_FAKE", "1")
    mgr = JobManager(tmp_path / "data", lib, tmp_path / "models", timeout_s=60)
    await mgr.start()
    try:
        job = await mgr.submit(_req(method="fast"), [("a.wav", _wav_bytes(_speech(4.0)))])
        done = await _settled(mgr, job.id, within=30)
    finally:
        await mgr.close()
    assert done.state == "succeeded", done.error
    build = lib.get(done.voice_id or "").build
    assert build is not None and build["method"] == "fast" and build["preset_start"] == "F1"


@pytest.fixture
def fresh_probe() -> AsyncIterator[None]:
    detect_local_builder.cache_clear()
    yield
    detect_local_builder.cache_clear()


def test_detect_local_builder_fake(monkeypatch: pytest.MonkeyPatch, fresh_probe: None) -> None:
    monkeypatch.setenv("SUPERTONIC_BUILDER_FAKE", "1")
    probe = detect_local_builder()
    assert probe == ProbeResult(True, "ok", "fake", 0, ("accurate", "fast"))
    monkeypatch.delenv("SUPERTONIC_BUILDER_FAKE")
    assert detect_local_builder() is probe  # cached for the process


@pytest.mark.parametrize(
    ("line", "available", "reason"),
    [
        (
            '{"type":"probe","torch":"2","cuda":false,"device":null,"vram_mb":0,"methods":[]}',
            False,
            "CUDA is unavailable",
        ),
        ('{"type":"error","code":"missing_dependencies","message":"no torch"}', False, "no torch"),
        ("garbage", False, "unreadable self-test output"),
    ],
)
def test_detect_local_builder_unavailable(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    fresh_probe: None,
    line: str,
    available: bool,
    reason: str,
) -> None:
    script = tmp_path / "probe.py"
    script.write_text(f"print({line!r})\n", encoding="utf-8")
    monkeypatch.setattr(availability, "_self_test_cmd", lambda python: [python, str(script)])
    probe = detect_local_builder()
    assert probe.available is available and reason in probe.reason


def test_detect_local_builder_timeout(monkeypatch: pytest.MonkeyPatch, fresh_probe: None) -> None:
    sleeper = [sys.executable, "-c", "import time; time.sleep(30)"]
    monkeypatch.setattr(availability, "_self_test_cmd", lambda python: sleeper)
    probe = detect_local_builder(timeout_s=0.5)
    assert not probe.available and "timed out" in probe.reason


@pytest.mark.parametrize(
    ("target", "state"),
    [
        ("log", "succeeded"),
        ("persist", "succeeded"),
        ("handler", "succeeded"),
        ("stdout", "failed"),
    ],
)
async def test_write_failures_never_stall_the_job(
    make_manager: ManagerFactory,
    modes: Callable[..., None],
    monkeypatch: pytest.MonkeyPatch,
    target: str,
    state: str,
) -> None:
    """A failing log/progress write (or a handler bug) must not stop the pipes draining."""
    modes("flood")

    def boom(*args: Any, **kwargs: Any) -> None:
        raise OSError(28, "No space left on device")

    if target == "log":
        monkeypatch.setattr(runlog.RunLog, "_write_log", boom)
    elif target == "stdout":  # every stdout line, including ``done``, is lost
        monkeypatch.setattr(runlog.RunLog, "_on_stdout", boom)
    elif target == "handler":
        monkeypatch.setattr(runlog.RunLog, "_on_progress", lambda self, event, line: 1 / 0)
    mgr = await make_manager(timeout_s=30.0)
    if target == "persist":  # every throttled progress save fails
        real = mgr._persist

        def flaky(job: Job) -> None:
            if job.state == "running" and job.progress is not None:
                boom()
            real(job)

        monkeypatch.setattr(mgr, "_persist", flaky)
    t0 = time.monotonic()
    done = await _settled(mgr, (await mgr.submit(_req(), FILES)).id)
    assert done.state == state, done.error
    assert time.monotonic() - t0 < 5
    if state == "failed":
        assert done.error is not None and done.error["code"] == "worker_failed"
        assert "No space left on device" in done.error["message"]


async def test_settle_persists_even_if_working_files_resist(
    make_manager: ManagerFactory, tmp_path: Path
) -> None:
    root = tmp_path / "data" / "jobs"
    folder = _write_job(root, "stuck", "running", datetime.now(UTC))
    (folder / "STOP").mkdir()  # unlink() fails on a directory
    (folder / "STOP" / "x").touch()
    mgr = await make_manager()
    assert mgr.get("stuck").state == "failed"
    saved = json.loads((folder / "job.json").read_text(encoding="utf-8"))
    assert saved["state"] == "failed" and saved["error"]["code"] == "interrupted"


async def test_submit_after_close_is_unavailable(make_manager: ManagerFactory) -> None:
    mgr = await make_manager()
    await mgr.close()
    with pytest.raises(ApiError) as exc:
        await mgr.submit(_req(), FILES)
    assert exc.value.status == 503 and exc.value.code == "builder_unavailable"


async def test_start_tolerates_odd_job_folders(
    make_manager: ManagerFactory, tmp_path: Path
) -> None:
    root = tmp_path / "data" / "jobs"
    naive = _write_job(root, "naive", "succeeded", datetime.now(UTC))
    data = json.loads((naive / "job.json").read_text(encoding="utf-8"))
    data["created_at"] = datetime.now().replace(tzinfo=None).isoformat()
    (naive / "job.json").write_text(json.dumps(data), encoding="utf-8")
    moved = _write_job(root, "moved", "succeeded", datetime.now(UTC))
    data = json.loads((moved / "job.json").read_text(encoding="utf-8"))
    data["id"] = "elsewhere"
    (moved / "job.json").write_text(json.dumps(data), encoding="utf-8")
    odd = _write_job(root, "odd", "succeeded", datetime.now(UTC))
    data = json.loads((odd / "job.json").read_text(encoding="utf-8"))
    data["created_at"] = "yesterday-ish"
    (odd / "job.json").write_text(json.dumps(data), encoding="utf-8")
    old_ts = time.time() - 8 * 86400
    for name, body in (("orphan-old", None), ("broken-old", "{not json"), ("broken-new", "{")):
        folder = root / name
        folder.mkdir()
        if body is not None:
            (folder / "job.json").write_text(body, encoding="utf-8")
        if name.endswith("old"):
            for p in (*folder.iterdir(), folder):
                os.utime(p, (old_ts, old_ts))
    for p in (*odd.iterdir(), odd):  # unparseable created_at: falls back to mtime
        os.utime(p, (old_ts, old_ts))
    outside = tmp_path / "outside.txt"
    outside.write_text("keep", encoding="utf-8")
    mgr = await make_manager()
    assert mgr.get("naive").state == "succeeded"
    assert mgr.get("moved").id == "moved"
    with pytest.raises(ApiError):
        mgr.get("elsewhere")
    assert not odd.exists()
    assert not (root / "orphan-old").exists() and not (root / "broken-old").exists()
    assert (root / "broken-new").exists() and outside.exists()


def _blocking_import(
    lib: VoiceLibrary, monkeypatch: pytest.MonkeyPatch
) -> tuple[threading.Event, threading.Event]:
    entered, release = threading.Event(), threading.Event()
    real = lib.import_style

    def slow(*args: Any, **kwargs: Any) -> Any:
        entered.set()
        release.wait(10)
        return real(*args, **kwargs)

    monkeypatch.setattr(lib, "import_style", slow)
    return entered, release


async def test_finish_during_import_is_unchanged(
    make_manager: ManagerFactory, lib: VoiceLibrary, monkeypatch: pytest.MonkeyPatch
) -> None:
    entered, release = _blocking_import(lib, monkeypatch)
    mgr = await make_manager()
    job = await mgr.submit(_req(), FILES)
    await _until(entered.is_set)
    assert (await mgr.finish(job.id)).stopping is False
    release.set()
    assert (await _settled(mgr, job.id)).state == "succeeded"


async def test_runner_cancel_during_import_finishes_the_import(
    make_manager: ManagerFactory, lib: VoiceLibrary, monkeypatch: pytest.MonkeyPatch
) -> None:
    entered, release = _blocking_import(lib, monkeypatch)
    mgr = await make_manager()
    job = await mgr.submit(_req(), FILES)
    await _until(entered.is_set)
    runner = mgr._runner
    assert runner is not None
    runner.cancel()
    await asyncio.sleep(0.05)
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await runner
    done = mgr.get(job.id)
    assert done.state == "succeeded" and done.voice_id == "narrator"
    assert lib.get("narrator").build is not None


def test_detect_local_builder_timeout_with_grandchild(
    monkeypatch: pytest.MonkeyPatch, fresh_probe: None
) -> None:
    """A grandchild holding the pipes must not keep the probe waiting past the timeout."""
    code = (
        "import subprocess, sys, time\n"
        "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])\n"
        "time.sleep(30)\n"
    )
    cmd = [sys.executable, "-c", code]
    monkeypatch.setattr(availability, "_self_test_cmd", lambda python: cmd)
    t0 = time.monotonic()
    probe = detect_local_builder(timeout_s=1.0)
    assert not probe.available and "timed out" in probe.reason
    assert time.monotonic() - t0 < 8


def test_failure_line_names_no_local_paths(tmp_path: Path) -> None:
    job = Job("j1", "running", _req(), "now", None, None, None, None, None, "local")
    log = runlog.RunLog(tmp_path, job, lambda: None)
    log._on_stderr(f"OSError: cannot open {Path.home() / 'secret' / 'model.onnx'}\n".encode())
    failure = log.failure(1)
    assert str(Path.home()) not in failure["message"]
    assert failure["message"].endswith("model.onnx")


async def test_spawn_failure_names_no_local_paths(
    make_manager: ManagerFactory, tmp_path: Path
) -> None:
    real = os.path.realpath(tmp_path)  # noqa: ASYNC240 - test setup
    missing = tmp_path / "no-such-python"
    mgr = await make_manager(worker_cmd=[str(missing)])
    done = await _settled(mgr, (await mgr.submit(_req(), FILES)).id)
    assert done.error is not None and done.error["code"] == "worker_failed"
    assert str(tmp_path) not in done.error["message"]
    assert real not in done.error["message"]
