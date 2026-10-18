"""RemoteBuilder: forward builds to a second app instance (the "Windows" builder) over ASGI."""

from __future__ import annotations

import asyncio
import json
import sys
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from pathlib import Path
from typing import Any

import httpx
import pytest

from fakes_builder import FAKE_WORKER
from supertonic_server.api import create_app
from supertonic_server.builder import Builder, BuildRequest, Job, PreparedAudio, jobs
from supertonic_server.builder.jobs import JobManager
from supertonic_server.builder.jobstore import write_job
from supertonic_server.builder.models import BUILD_METHODS
from supertonic_server.builder.remote import RemoteBuilder
from supertonic_server.core.config import Settings
from supertonic_server.core.errors import ApiError
from supertonic_server.engine import Engine
from supertonic_server.voices import VoiceLibrary

BASE = "http://win:8787"
HOST = "win:8787"
KEY = "win-secret"
FILES = [("ref.wav", b"fake-audio")]
TERMINAL = {"succeeded", "failed", "cancelled"}


def _req(**kw: Any) -> BuildRequest:
    args: dict[str, Any] = {
        "name": "Narrator",
        "description": "deep",
        "tags": ["a"],
        "source_note": "my own voice",
        "consent": True,
        "method": "fast",
    }
    return BuildRequest(**{**args, **kw})


def _fake_prepare(files: Sequence[tuple[str, bytes]], out_path: Path) -> PreparedAudio:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(b"RIFF-fake")
    return PreparedAudio(out_path, 5.0, 4.0, [n for n, _ in files])


class Switch(httpx.AsyncBaseTransport):
    """Delegates to the remote app, or fails like a dead network while ``down``."""

    def __init__(self, inner: httpx.AsyncBaseTransport) -> None:
        self.inner = inner
        self.down = False

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if self.down:
            raise httpx.ConnectError("connection refused", request=request)
        return await self.inner.handle_async_request(request)


class Remote:
    """The "Windows" side: a JobManager behind its own app, reached through ``switch``."""

    def __init__(self, manager: JobManager, lib: VoiceLibrary, switch: Switch) -> None:
        self.manager, self.lib, self.switch = manager, lib, switch
        self.http = httpx.AsyncClient(transport=switch, base_url=BASE)


RemoteFactory = Callable[..., Awaitable[Remote]]
BuilderFactory = Callable[..., Awaitable[RemoteBuilder]]


@pytest.fixture
def control(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "control"
    path.mkdir()
    monkeypatch.setenv("FAKE_BUILDER_DIR", str(path))
    monkeypatch.setattr(jobs, "prepare_reference", _fake_prepare)
    return path


@pytest.fixture
async def make_remote(
    tmp_path: Path, lib: VoiceLibrary, engine: Engine, control: Path
) -> AsyncIterator[RemoteFactory]:
    made: list[Remote] = []

    async def factory(builder: bool = True, **kw: Any) -> Remote:
        win = tmp_path / "win"
        rlib = VoiceLibrary(lib.presets_dir, win / "custom")
        args: dict[str, Any] = {"timeout_s": 30.0, "worker_cmd": [sys.executable, FAKE_WORKER]}
        mgr = JobManager(win / "data", rlib, win / "models", **{**args, **kw})
        await mgr.start()
        settings = Settings(data_dir=win / "data", api_key=KEY)
        app = create_app(settings, engine, rlib, mgr if builder else None)
        remote = Remote(mgr, rlib, Switch(httpx.ASGITransport(app=app)))
        made.append(remote)
        return remote

    yield factory
    for remote in made:
        await remote.manager.close()
        await remote.http.aclose()


@pytest.fixture
async def make_builder(tmp_path: Path, lib: VoiceLibrary) -> AsyncIterator[BuilderFactory]:
    made: list[RemoteBuilder] = []

    async def factory(remote: Remote, **kw: Any) -> RemoteBuilder:
        args: dict[str, Any] = {"http": remote.http, "poll_s": 0.02, "lost_after_s": 5.0}
        rb = RemoteBuilder(BASE, KEY, lib, tmp_path / "data", **{**args, **kw})
        await rb.start()
        made.append(rb)
        return rb

    yield factory
    for rb in made:
        await rb.close()


async def _until(pred: Callable[[], bool], within: float = 10.0) -> None:
    deadline = time.monotonic() + within
    while not pred():
        if time.monotonic() > deadline:
            raise AssertionError("condition not met in time")
        await asyncio.sleep(0.01)


async def _settled(rb: RemoteBuilder, job_id: str, within: float = 10.0) -> Job:
    await _until(lambda: rb.get(job_id).state in TERMINAL, within)
    return rb.get(job_id)


def _custom(lib: VoiceLibrary) -> list[str]:
    return [v.id for v in lib.list() if v.kind == "custom"]


async def test_satisfies_builder_protocol(
    make_remote: RemoteFactory, make_builder: BuilderFactory
) -> None:
    rb = await make_builder(await make_remote())
    builder: Builder = rb
    assert builder.methods == BUILD_METHODS
    assert rb.detail() == {"host": HOST, "methods": ["accurate", "fast"]}


async def test_forward_end_to_end(
    make_remote: RemoteFactory,
    make_builder: BuilderFactory,
    lib: VoiceLibrary,
    tmp_path: Path,
    control: Path,
) -> None:
    remote = await make_remote(methods=("fast",))
    rb = await make_builder(remote)
    job = await rb.submit(_req(), FILES)
    assert job.builder == f"remote:{HOST}" and job.remote_id is not None
    assert rb.methods == ("fast",)
    done = await _settled(rb, job.id)
    assert done.state == "succeeded", done.error
    remote_job = remote.manager.get(job.remote_id)
    assert remote_job.state == "succeeded" and done.remote_voice_id == remote_job.voice_id
    assert done.voice_id is not None
    voice = lib.get(done.voice_id)
    assert voice.kind == "custom" and voice.name == "Narrator" and voice.tags == ["a"]
    assert voice.source_note == "my own voice" and voice.description == "deep"
    assert voice.build is not None
    assert voice.build["builder"] == f"remote:{HOST}" and voice.build["method"] == "fast"
    assert voice.build["loss"] == 0.25 and "seconds" in voice.build
    assert lib.style_json(done.voice_id) == remote.lib.style_json(remote_job.voice_id or "")
    argv = json.loads((control / "run-0.json").read_text())["argv"]
    assert argv[argv.index("--method") + 1] == "fast"
    saved = json.loads((tmp_path / "data" / "jobs" / job.id / "job.json").read_text())
    assert saved["remote_id"] == job.remote_id and saved["state"] == "succeeded"
    assert [j.id for j in rb.list()] == [job.id]


async def test_unreachable_at_submit(
    make_remote: RemoteFactory, make_builder: BuilderFactory
) -> None:
    remote = await make_remote()
    rb = await make_builder(remote)
    remote.switch.down = True
    with pytest.raises(ApiError) as info:
        await rb.submit(_req(), FILES)
    assert info.value.status == 503 and info.value.code == "builder_unavailable"
    assert info.value.message.startswith(f"Voice builder at {HOST} is not reachable: ")
    assert rb.list() == []


async def test_remote_without_local_builder(
    make_remote: RemoteFactory, make_builder: BuilderFactory
) -> None:
    rb = await make_builder(await make_remote(builder=False))
    with pytest.raises(ApiError) as info:
        await rb.submit(_req(), FILES)
    assert info.value.status == 503 and info.value.code == "builder_unavailable"
    assert "builder" in info.value.message


async def test_wrong_key_is_unavailable(
    make_remote: RemoteFactory, make_builder: BuilderFactory, lib: VoiceLibrary, tmp_path: Path
) -> None:
    remote = await make_remote()
    rb = RemoteBuilder(BASE, "wrong", lib, tmp_path / "data", http=remote.http)
    await rb.start()
    try:
        with pytest.raises(ApiError) as info:
            await rb.submit(_req(), FILES)
    finally:
        await rb.close()
    assert info.value.status == 503 and info.value.code == "builder_unavailable"
    assert "API key" in info.value.message


@pytest.mark.parametrize(
    ("kind", "code", "param"),
    [
        ("consent", "consent_required", "consent"),
        ("method", "method_unavailable", "method"),
        ("audio", "invalid_reference_audio", None),
    ],
)
async def test_remote_errors_propagate(
    make_remote: RemoteFactory,
    make_builder: BuilderFactory,
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
    code: str,
    param: str | None,
) -> None:
    from supertonic_server.builder import audio_prep

    remote = await make_remote(methods=("accurate",))
    rb = await make_builder(remote)
    req, files = _req(), FILES
    if kind == "consent":
        req = _req(consent=False)
    elif kind == "audio":
        req = _req(method="accurate")
        files = [("empty.wav", b"")]
        monkeypatch.setattr(jobs, "prepare_reference", audio_prep.prepare_reference)
    with pytest.raises(ApiError) as info:
        await rb.submit(req, files)
    assert info.value.status == 400 and info.value.code == code
    if param is not None:
        assert info.value.param == param
    assert rb.list() == [] and remote.manager.list() == []


async def test_remote_failure_is_mirrored(
    make_remote: RemoteFactory,
    make_builder: BuilderFactory,
    lib: VoiceLibrary,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FAKE_BUILDER_MODES", "error:out_of_memory")
    rb = await make_builder(await make_remote())
    done = await _settled(rb, (await rb.submit(_req(), FILES)).id)
    assert done.state == "failed" and done.error is not None
    assert done.error["code"] == "out_of_memory"
    assert _custom(lib) == []


async def _running(rb: RemoteBuilder, job_id: str) -> None:
    await _until(lambda: rb.get(job_id).state == "running")


async def test_remote_disappears_mid_job_is_builder_lost(
    make_remote: RemoteFactory,
    make_builder: BuilderFactory,
    lib: VoiceLibrary,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FAKE_BUILDER_MODES", "gate")
    remote = await make_remote()
    rb = await make_builder(remote, lost_after_s=0.4)
    job = await rb.submit(_req(), FILES)
    await _running(rb, job.id)
    remote.switch.down = True
    lost_at = time.monotonic()
    await asyncio.sleep(0.25)
    assert rb.get(job.id).state == "running"  # still inside the lost_after_s window
    done = await _settled(rb, job.id)
    # the window starts at the last good poll, at most one poll_s before the switch
    assert time.monotonic() - lost_at >= 0.4 - 0.02
    assert done.state == "failed" and done.error is not None
    assert done.error["code"] == "builder_lost" and HOST in done.error["message"]
    assert done.voice_id is None and _custom(lib) == []


async def test_transient_failure_does_not_fail_job(
    make_remote: RemoteFactory,
    make_builder: BuilderFactory,
    control: Path,
    lib: VoiceLibrary,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FAKE_BUILDER_MODES", "gate")
    remote = await make_remote()
    rb = await make_builder(remote, lost_after_s=1.5)
    job = await rb.submit(_req(), FILES)
    await _running(rb, job.id)
    remote.switch.down = True
    await asyncio.sleep(0.3)
    assert rb.get(job.id).state == "running"
    remote.switch.down = False
    (control / "go").touch()
    done = await _settled(rb, job.id)
    assert done.state == "succeeded" and _custom(lib) == [done.voice_id]


async def test_cancel_propagates(
    make_remote: RemoteFactory,
    make_builder: BuilderFactory,
    lib: VoiceLibrary,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FAKE_BUILDER_MODES", "gate")
    remote = await make_remote()
    rb = await make_builder(remote)
    job = await rb.submit(_req(), FILES)
    await _running(rb, job.id)
    cancelled = await rb.cancel(job.id)
    assert cancelled.state == "cancelled"
    assert remote.manager.get(job.remote_id or "").state == "cancelled"
    await asyncio.sleep(0.1)
    assert rb.get(job.id).state == "cancelled" and _custom(lib) == []
    assert (await rb.cancel(job.id)).state == "cancelled"


async def test_cancel_while_builder_unreachable_says_so(
    make_remote: RemoteFactory,
    make_builder: BuilderFactory,
    lib: VoiceLibrary,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FAKE_BUILDER_MODES", "gate")
    remote = await make_remote()
    rb = await make_builder(remote)
    job = await rb.submit(_req(), FILES)
    await _running(rb, job.id)
    remote.switch.down = True
    cancelled = await rb.cancel(job.id)
    assert cancelled.state == "cancelled" and _custom(lib) == []
    assert cancelled.error == {
        "code": "builder_unreachable",
        "message": "Could not reach the builder; the build may still be running there.",
    }
    assert remote.manager.get(job.remote_id or "").state == "running"
    reloaded = json.loads((rb._root / job.id / "job.json").read_text(encoding="utf-8"))
    assert reloaded["error"]["code"] == "builder_unreachable"


async def test_finish_propagates(
    make_remote: RemoteFactory,
    make_builder: BuilderFactory,
    lib: VoiceLibrary,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FAKE_BUILDER_MODES", "gate")
    remote = await make_remote()
    rb = await make_builder(remote)
    job = await rb.submit(_req(), FILES)
    await _running(rb, job.id)
    assert (await rb.finish(job.id)).stopping is True
    done = await _settled(rb, job.id)
    assert done.state == "succeeded" and done.voice_id is not None
    build = lib.get(done.voice_id).build
    assert build is not None and build["stopped_early"] is True


async def test_finish_unreachable_and_unknown_job(
    make_remote: RemoteFactory, make_builder: BuilderFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_BUILDER_MODES", "gate")
    remote = await make_remote()
    rb = await make_builder(remote)
    with pytest.raises(ApiError) as missing:
        rb.get("nope")
    assert missing.value.code == "job_not_found"
    job = await rb.submit(_req(), FILES)
    await _running(rb, job.id)
    remote.switch.down = True
    with pytest.raises(ApiError) as info:
        await rb.finish(job.id)
    assert info.value.status == 503 and info.value.code == "builder_unavailable"


async def test_restart_resumes_polling(
    make_remote: RemoteFactory,
    make_builder: BuilderFactory,
    control: Path,
    lib: VoiceLibrary,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FAKE_BUILDER_MODES", "gate")
    remote = await make_remote()
    first = await make_builder(remote)
    job = await first.submit(_req(), FILES)
    await _running(first, job.id)
    await first.close()
    second = await make_builder(remote)
    assert second.get(job.id).state == "running"
    (control / "go").touch()
    done = await _settled(second, job.id)
    assert done.state == "succeeded" and _custom(lib) == [done.voice_id]


async def test_restart_marks_unmirrored_job_interrupted(
    make_remote: RemoteFactory, make_builder: BuilderFactory, tmp_path: Path
) -> None:
    root = tmp_path / "data" / "jobs" / "orphan"
    root.mkdir(parents=True)
    job = Job("orphan", "running", _req(), "2099-01-01T00:00:00+00:00", None, None, None, None,
              None, "local")  # fmt: skip
    write_job(root, job)
    rb = await make_builder(await make_remote())
    got = rb.get("orphan")
    assert got.state == "failed" and got.error is not None and got.error["code"] == "interrupted"


async def test_submit_after_close(make_remote: RemoteFactory, make_builder: BuilderFactory) -> None:
    rb = await make_builder(await make_remote())
    await rb.close()
    with pytest.raises(ApiError) as info:
        await rb.submit(_req(), FILES)
    assert info.value.code == "builder_unavailable"


async def test_start_with_unreachable_remote_does_not_raise(
    lib: VoiceLibrary, tmp_path: Path
) -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    http = httpx.AsyncClient(transport=httpx.MockTransport(refuse))
    rb = RemoteBuilder(BASE, None, lib, tmp_path / "data", http=http)
    await rb.start()
    await asyncio.sleep(0.05)
    assert rb.methods == BUILD_METHODS
    await rb.close()
    await http.aclose()


def _mock(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.mark.parametrize("bad", [{"consent": False}, {"name": "  "}])
async def test_invalid_request_rejected_locally_before_any_contact(
    lib: VoiceLibrary, tmp_path: Path, bad: dict[str, Any]
) -> None:
    seen: list[httpx.Request] = []

    def refuse(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        raise httpx.ConnectError("connection refused", request=request)

    http = _mock(refuse)
    rb = RemoteBuilder(BASE, None, lib, tmp_path / "data", http=http)
    await rb.start()
    await asyncio.sleep(0.05)  # let the background method refresh run and fail
    seen.clear()
    try:
        with pytest.raises(ApiError) as info:
            await rb.submit(_req(**bad), FILES)
    finally:
        await rb.close()
        await http.aclose()
    assert info.value.status == 400
    assert info.value.code in {"consent_required", "invalid_request"}
    assert seen == [] and rb.list() == []


async def test_concurrent_cancels_racing_remote_success_import_once(
    make_remote: RemoteFactory,
    make_builder: BuilderFactory,
    control: Path,
    lib: VoiceLibrary,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FAKE_BUILDER_MODES", "gate")
    remote = await make_remote()
    rb = await make_builder(remote, poll_s=30.0)  # the first poll never comes in time
    job = await rb.submit(_req(), FILES)
    rid = job.remote_id or ""
    await _until(lambda: remote.manager.get(rid).state == "running")
    (control / "go").touch()
    await _until(lambda: remote.manager.get(rid).state == "succeeded")
    first, second = await asyncio.gather(rb.cancel(job.id), rb.cancel(job.id))
    done = await _settled(rb, job.id)
    assert done.state == "succeeded" and _custom(lib) == [done.voice_id]
    await rb.close()
    leftover = [t for t in asyncio.all_tasks() if t.get_name().startswith("remote-build-")]
    assert leftover == []


async def test_restart_after_import_before_settle_does_not_import_twice(
    make_remote: RemoteFactory, make_builder: BuilderFactory, lib: VoiceLibrary, tmp_path: Path
) -> None:
    remote = await make_remote()
    first = await make_builder(remote)
    job = await first.submit(_req(), FILES)
    done = await _settled(first, job.id)
    assert done.state == "succeeded"
    await first.close()
    path = tmp_path / "data" / "jobs" / job.id / "job.json"
    saved = json.loads(path.read_text())
    saved.update(state="running", voice_id=None, remote_voice_id=None, finished_at=None)
    path.write_text(json.dumps(saved))  # as if the server died between import and settle
    second = await make_builder(remote)
    again = await _settled(second, job.id)
    assert again.state == "succeeded" and again.voice_id == done.voice_id
    assert _custom(lib) == [done.voice_id]


async def test_mirror_write_error_keeps_polling(
    make_remote: RemoteFactory,
    make_builder: BuilderFactory,
    control: Path,
    lib: VoiceLibrary,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from supertonic_server.builder import remote as remote_mod

    monkeypatch.setenv("FAKE_BUILDER_MODES", "gate")
    rb = await make_builder(await make_remote())
    job = await rb.submit(_req(), FILES)

    def flaky(folder: Path, j: Job) -> None:
        if j.state not in TERMINAL:
            raise OSError("disk full")
        write_job(folder, j)

    monkeypatch.setattr(remote_mod, "write_job", flaky)
    await _running(rb, job.id)
    (control / "go").touch()
    done = await _settled(rb, job.id)
    assert done.state == "succeeded" and _custom(lib) == [done.voice_id]


async def test_start_twice_leaks_no_task(lib: VoiceLibrary, tmp_path: Path) -> None:
    async def hang(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(30)  # the method refresh stays in flight
        return httpx.Response(200, json={})

    def refreshes() -> list[asyncio.Task[Any]]:
        return [t for t in asyncio.all_tasks() if t.get_name() == "builder-methods"]

    http = httpx.AsyncClient(transport=httpx.MockTransport(hang))
    rb = RemoteBuilder(BASE, None, lib, tmp_path / "data", http=http)
    await rb.start()
    await rb.start()
    await asyncio.sleep(0)
    assert len(refreshes()) == 1
    await rb.close()
    await http.aclose()
    assert refreshes() == []


async def test_non_json_5xx_at_submit_is_unavailable(lib: VoiceLibrary, tmp_path: Path) -> None:
    def broken(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/health":
            return httpx.Response(200, json={"builder": "local", "builder_detail": None})
        return httpx.Response(500, text="Internal Server Error")

    http = _mock(broken)
    rb = RemoteBuilder(BASE, None, lib, tmp_path / "data", http=http)
    await rb.start()
    try:
        with pytest.raises(ApiError) as info:
            await rb.submit(_req(), FILES)
    finally:
        await rb.close()
        await http.aclose()
    assert info.value.status == 503 and info.value.code == "builder_unavailable"
    assert "HTTP 500" in info.value.message


async def test_finish_error_names_the_local_job(
    make_remote: RemoteFactory, make_builder: BuilderFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_BUILDER_MODES", "gate")
    rb = await make_builder(await make_remote())
    await _running(rb, (await rb.submit(_req(), FILES)).id)
    queued = await rb.submit(_req(name="Second"), FILES)  # waits behind the first remotely
    with pytest.raises(ApiError) as info:
        await rb.finish(queued.id)
    assert info.value.status == 409 and info.value.code == "job_not_running"
    assert queued.id in info.value.message and (queued.remote_id or "") not in info.value.message


async def test_unreachable_message_hides_url_and_credentials(
    lib: VoiceLibrary, tmp_path: Path
) -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"cannot reach {request.url}", request=request)

    http = _mock(refuse)
    rb = RemoteBuilder("http://admin:hunter2@win:8787", None, lib, tmp_path / "data", http=http)
    await rb.start()
    try:
        with pytest.raises(ApiError) as info:
            await rb.submit(_req(), FILES)
    finally:
        await rb.close()
        await http.aclose()
    message = info.value.message
    assert message.startswith(f"Voice builder at {HOST} is not reachable: ")
    assert "hunter2" not in message and "admin" not in message and "http://" not in message
