"""Voice build and job endpoints, driven by a real JobManager over the fake worker."""

from __future__ import annotations

import asyncio
import json
import sys
import time
from collections.abc import AsyncIterator, Callable, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx
import pytest

from fakes_builder import FAKE_WORKER
from supertonic_server.api import create_app
from supertonic_server.builder import Builder, PreparedAudio, jobs
from supertonic_server.builder.jobs import JobManager
from supertonic_server.builder.remote import RemoteBuilder

if TYPE_CHECKING:
    from fastapi import FastAPI

    from supertonic_server.core.config import Settings
    from supertonic_server.engine import Engine
    from supertonic_server.voices import VoiceLibrary

FORM = {"name": "Narrator", "source_note": "my own voice", "consent": "true", "tags": "a, b"}
AppClient = Callable[["FastAPI"], httpx.AsyncClient]
TERMINAL = {"succeeded", "failed", "cancelled"}


def _files(n: int = 1) -> list[tuple[str, tuple[str, bytes, str]]]:
    return [("files", (f"ref{i}.wav", b"fake-audio", "audio/wav")) for i in range(n)]


def _fake_prepare(files: Sequence[tuple[str, bytes]], out_path: Path) -> PreparedAudio:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(b"RIFF-fake")
    return PreparedAudio(out_path, 5.0, 4.0, [n for n, _ in files])


@pytest.fixture
def control(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "control"
    path.mkdir()
    monkeypatch.setenv("FAKE_BUILDER_DIR", str(path))
    return path


@pytest.fixture
async def manager(
    tmp_path: Path, lib: VoiceLibrary, control: Path, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[JobManager]:
    monkeypatch.setattr(jobs, "prepare_reference", _fake_prepare)
    mgr = JobManager(
        tmp_path / "data",
        lib,
        tmp_path / "models",
        timeout_s=30.0,
        worker_cmd=[sys.executable, FAKE_WORKER],
    )
    await mgr.start()
    yield mgr
    await mgr.close()


@pytest.fixture
async def bclient(
    settings: Settings,
    engine: Engine,
    lib: VoiceLibrary,
    manager: JobManager,
    app_client: AppClient,
) -> AsyncIterator[httpx.AsyncClient]:
    async with app_client(create_app(settings, engine, lib, manager)) as c:
        yield c


async def _wait(client: httpx.AsyncClient, job_id: str, within: float = 10.0) -> dict[str, Any]:
    deadline = time.monotonic() + within
    while True:
        job: dict[str, Any] = (await client.get(f"/v1/jobs/{job_id}")).json()
        if job["state"] in TERMINAL:
            return job
        assert time.monotonic() < deadline, f"job still {job['state']}"
        await asyncio.sleep(0.02)


def test_job_manager_satisfies_builder_protocol(manager: JobManager) -> None:
    builder: Builder = manager
    assert builder.methods == ("accurate", "fast")


async def test_build_happy_path(bclient: httpx.AsyncClient, control: Path) -> None:
    r = await bclient.post("/v1/voices/build", data=FORM, files=_files())
    assert r.status_code == 202
    job = r.json()
    assert job["state"] in {"queued", "running"} and job["request"]["tags"] == ["a", "b"]
    done = await _wait(bclient, job["id"])
    assert done["state"] == "succeeded", done["error"]
    voice = (await bclient.get(f"/v1/voices/{done['voice_id']}")).json()
    assert voice["kind"] == "custom" and voice["build"]["method"] == "accurate"
    assert voice["source_note"] == "my own voice"
    listed = (await bclient.get("/v1/jobs")).json()["data"]
    assert [j["id"] for j in listed] == [job["id"]]


async def test_method_fast_reaches_worker(bclient: httpx.AsyncClient, control: Path) -> None:
    r = await bclient.post("/v1/voices/build", data={**FORM, "method": "fast"}, files=_files(3))
    assert r.status_code == 202
    await _wait(bclient, r.json()["id"])
    argv = json.loads((control / "run-0.json").read_text())["argv"]
    assert argv[argv.index("--method") + 1] == "fast"


async def test_invalid_method(bclient: httpx.AsyncClient) -> None:
    r = await bclient.post("/v1/voices/build", data={**FORM, "method": "slow"}, files=_files())
    err = r.json()["error"]
    assert r.status_code == 400 and err["code"] == "invalid_request" and err["param"] == "method"


async def test_missing_consent(bclient: httpx.AsyncClient) -> None:
    form = {k: v for k, v in FORM.items() if k != "consent"}
    r = await bclient.post("/v1/voices/build", data=form, files=_files())
    assert r.status_code == 400 and r.json()["error"]["code"] == "consent_required"
    r = await bclient.post("/v1/voices/build", data={**FORM, "consent": "false"}, files=_files())
    assert r.status_code == 400 and r.json()["error"]["code"] == "consent_required"


@pytest.mark.parametrize("count", [0, 4])
async def test_file_count(bclient: httpx.AsyncClient, count: int) -> None:
    r = await bclient.post("/v1/voices/build", data=FORM, files=_files(count) or None)
    err = r.json()["error"]
    assert r.status_code == 400 and err["code"] == "invalid_request" and err["param"] == "files"


async def test_oversize_upload_rejected_by_guard(bclient: httpx.AsyncClient) -> None:
    big = [("files", ("big.wav", b"\0" * (26 * 1024 * 1024), "audio/wav"))]
    r = await bclient.post("/v1/voices/build", data=FORM, files=big)
    assert r.status_code == 413 and r.json()["error"]["code"] == "payload_too_large"


async def test_finish_stops_early(
    bclient: httpx.AsyncClient, control: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_BUILDER_MODES", "gate")
    job = (await bclient.post("/v1/voices/build", data=FORM, files=_files())).json()
    deadline = time.monotonic() + 10
    while (await bclient.get(f"/v1/jobs/{job['id']}")).json()["state"] != "running":
        assert time.monotonic() < deadline
        await asyncio.sleep(0.02)
    r = await bclient.post(f"/v1/jobs/{job['id']}/finish")
    assert r.status_code == 200 and r.json()["stopping"] is True
    done = await _wait(bclient, job["id"])
    assert done["state"] == "succeeded"
    voice = (await bclient.get(f"/v1/voices/{done['voice_id']}")).json()
    assert voice["build"]["stopped_early"] is True


async def test_cancel_and_unknown_job(
    bclient: httpx.AsyncClient, control: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_BUILDER_MODES", "gate")
    job = (await bclient.post("/v1/voices/build", data=FORM, files=_files())).json()
    r = await bclient.delete(f"/v1/jobs/{job['id']}")
    assert r.status_code == 200 and r.json()["state"] == "cancelled"
    missing = await bclient.get("/v1/jobs/nope")
    assert missing.status_code == 404 and missing.json()["error"]["code"] == "job_not_found"


async def test_no_builder_is_503_with_hint(client: httpx.AsyncClient) -> None:
    r = await client.post("/v1/voices/build", data=FORM, files=_files())
    err = r.json()["error"]
    assert r.status_code == 503 and err["code"] == "builder_unavailable"
    assert "SUPERTONIC_BUILDER_URL" in err["message"] and "builder extra" in err["message"]
    for method, path in [("GET", "/v1/jobs"), ("GET", "/v1/jobs/x"), ("DELETE", "/v1/jobs/x")]:
        assert (await client.request(method, path)).status_code == 503


async def test_endpoints_require_auth(
    settings: Settings,
    engine: Engine,
    lib: VoiceLibrary,
    manager: JobManager,
    app_client: AppClient,
) -> None:
    keyed = settings.model_copy(update={"api_key": "secret"})
    async with app_client(create_app(keyed, engine, lib, manager)) as c:
        assert (await c.get("/v1/jobs")).status_code == 401
        assert (await c.post("/v1/voices/build", data=FORM, files=_files())).status_code == 401
        assert (await c.post("/v1/jobs/x/finish")).status_code == 401
        ok = await c.get("/v1/jobs", headers={"Authorization": "Bearer secret"})
        assert ok.status_code == 200
        assert (await c.get("/v1/health")).json()["builder"] == "local"


async def test_health_reflects_builder(
    bclient: httpx.AsyncClient, client: httpx.AsyncClient
) -> None:
    body = (await bclient.get("/v1/health")).json()
    assert body["builder"] == "local"
    assert body["builder_detail"] == {
        "device": None,
        "vram_mb": None,
        "methods": ["accurate", "fast"],
    }
    none = (await client.get("/v1/health")).json()
    assert none["builder"] == "none" and none["builder_detail"] is None


async def test_start_builder_modes(
    settings: Settings, lib: VoiceLibrary, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from supertonic_server.api import builder_boot
    from supertonic_server.builder.availability import ProbeResult

    probe = ProbeResult(True, "ok", "RTX 4050", 6144, ("fast",))
    monkeypatch.setattr(builder_boot, "detect_local_builder", lambda: probe)
    off = settings.model_copy(update={"builder": "off"})
    assert await builder_boot.start_builder(off, lib, tmp_path) is None
    url = settings.model_copy(update={"builder_url": "http://127.0.0.1:9/", "builder": "local"})
    remote = await builder_boot.start_builder(url, lib, tmp_path)
    try:  # an unreachable remote does not stop startup; submit-time health gates builds
        assert isinstance(remote, RemoteBuilder) and remote.kind == "remote"
        assert remote.detail() == {"host": "127.0.0.1:9", "methods": ["accurate", "fast"]}
    finally:
        assert remote is not None
        await remote.close()
    mgr = await builder_boot.start_builder(settings, lib, tmp_path)
    assert mgr is not None
    try:
        assert mgr.methods == ("fast",) and mgr.kind == "local"
        assert mgr.detail() == {"device": "RTX 4050", "vram_mb": 6144, "methods": ["fast"]}
    finally:
        await mgr.close()
    no = ProbeResult(False, "CUDA is unavailable", None, None, ())
    monkeypatch.setattr(builder_boot, "detect_local_builder", lambda: no)
    assert await builder_boot.start_builder(settings, lib, tmp_path) is None
    local = settings.model_copy(update={"builder": "local"})
    assert await builder_boot.start_builder(local, lib, tmp_path) is None


async def test_builder_busy_is_503(
    bclient: httpx.AsyncClient, manager: JobManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    from supertonic_server.core.errors import builder_busy

    async def busy(*args: Any, **kwargs: Any) -> Any:
        raise builder_busy()

    monkeypatch.setattr(manager, "submit", busy)
    r = await bclient.post("/v1/voices/build", data=FORM, files=_files())
    assert r.status_code == 503 and r.json()["error"]["code"] == "builder_busy"


async def test_blank_source_note(bclient: httpx.AsyncClient) -> None:
    r = await bclient.post("/v1/voices/build", data={**FORM, "source_note": "  "}, files=_files())
    err = r.json()["error"]
    assert r.status_code == 400 and err["code"] == "consent_required"
    assert err["param"] == "source_note"


async def test_zero_byte_file(bclient: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from supertonic_server.builder import audio_prep

    monkeypatch.setattr(jobs, "prepare_reference", audio_prep.prepare_reference)
    empty = [("files", ("empty.wav", b"", "audio/wav"))]
    r = await bclient.post("/v1/voices/build", data=FORM, files=empty)
    assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_reference_audio"


async def test_unknown_job_cancel_and_finish(bclient: httpx.AsyncClient) -> None:
    for r in (await bclient.delete("/v1/jobs/nope"), await bclient.post("/v1/jobs/nope/finish")):
        assert r.status_code == 404 and r.json()["error"]["code"] == "job_not_found"


async def test_delete_requires_auth(
    settings: Settings,
    engine: Engine,
    lib: VoiceLibrary,
    manager: JobManager,
    app_client: AppClient,
) -> None:
    keyed = settings.model_copy(update={"api_key": "secret"})
    async with app_client(create_app(keyed, engine, lib, manager)) as c:
        assert (await c.delete("/v1/jobs/x")).status_code == 401


async def test_text_entry_under_files_rejected(bclient: httpx.AsyncClient) -> None:
    r = await bclient.post("/v1/voices/build", data={**FORM, "files": "oops"})
    err = r.json()["error"]
    assert r.status_code == 400 and err["param"] == "files" and "file uploads" in err["message"]
    mixed = await bclient.post("/v1/voices/build", data={**FORM, "files": "oops"}, files=_files())
    assert mixed.status_code == 400 and mixed.json()["error"]["param"] == "files"


@pytest.mark.parametrize(
    ("extra", "param"),
    [
        ({"description": "x" * 501}, "description"),
        ({"tags": ",".join("t" for _ in range(21))}, "tags"),
        ({"tags": "x" * 41}, "tags"),
    ],
)
async def test_description_and_tag_bounds(
    bclient: httpx.AsyncClient, extra: dict[str, str], param: str
) -> None:
    r = await bclient.post("/v1/voices/build", data={**FORM, **extra}, files=_files())
    err = r.json()["error"]
    assert r.status_code == 400 and err["code"] == "invalid_request" and err["param"] == param


def test_builder_needs_engine_and_library(settings: Settings, manager: JobManager) -> None:
    with pytest.raises(ValueError, match="injected builder"):
        create_app(settings, builder=manager)


class _FakeBuilder:
    kind = "local"

    def __init__(self) -> None:
        self.closed = False

    def detail(self) -> dict[str, Any]:
        return {"device": "X", "vram_mb": 1, "methods": ["fast"]}

    async def close(self) -> None:
        self.closed = True


def _boot_app(
    settings: Settings, engine: Engine, lib: VoiceLibrary, monkeypatch: pytest.MonkeyPatch
) -> FastAPI:
    from supertonic_server.api import app as app_mod

    monkeypatch.setattr(app_mod, "load_engine", lambda s: (engine, lib.presets_dir))
    return create_app(settings)


async def test_lifespan_assigns_and_closes_builder(
    settings: Settings,
    engine: Engine,
    lib: VoiceLibrary,
    monkeypatch: pytest.MonkeyPatch,
    app_client: AppClient,
) -> None:
    from supertonic_server.api import app as app_mod

    fake = _FakeBuilder()

    async def boot(*args: Any) -> Any:
        return fake

    monkeypatch.setattr(app_mod, "start_builder", boot)
    app = _boot_app(settings, engine, lib, monkeypatch)
    async with app.router.lifespan_context(app):
        assert app.state.app_state.builder is fake
        async with app_client(app) as c:
            health = (await c.get("/v1/health")).json()
            assert health["builder"] == "local" and health["builder_detail"]["vram_mb"] == 1
    assert fake.closed


@pytest.mark.parametrize("failure", ["probe", "start"])
async def test_builder_failure_does_not_stop_server(
    settings: Settings,
    engine: Engine,
    lib: VoiceLibrary,
    monkeypatch: pytest.MonkeyPatch,
    app_client: AppClient,
    failure: str,
) -> None:
    from supertonic_server.api import builder_boot
    from supertonic_server.builder.availability import ProbeResult

    def probe() -> ProbeResult:
        if failure == "probe":
            raise RuntimeError("probe exploded")
        return ProbeResult(True, "ok", "GPU", 1, ("fast",))

    async def bad_start(self: JobManager) -> None:
        raise OSError("disk gone")

    monkeypatch.setattr(builder_boot, "detect_local_builder", probe)
    monkeypatch.setattr(JobManager, "start", bad_start)
    closed: list[bool] = []
    monkeypatch.setattr(engine.scheduler, "close", lambda: closed.append(True))
    app = _boot_app(settings, engine, lib, monkeypatch)
    async with app.router.lifespan_context(app), app_client(app) as c:
        health = (await c.get("/v1/health")).json()
        assert health["builder"] == "none" and health["builder_detail"] is None
    assert closed == [True]


async def test_forwarded_build_through_the_api(
    settings: Settings,
    engine: Engine,
    lib: VoiceLibrary,
    manager: JobManager,
    app_client: AppClient,
    control: Path,
    tmp_path: Path,
) -> None:
    """A builder-less instance forwards to a second app (the builder) and imports the voice."""
    win = create_app(settings.model_copy(update={"api_key": "k"}), engine, lib, manager)
    http = httpx.AsyncClient(transport=httpx.ASGITransport(app=win), base_url="http://win:8787")
    rb = RemoteBuilder("http://win:8787", "k", lib, tmp_path / "mac", http=http, poll_s=0.02)
    await rb.start()
    try:
        async with app_client(create_app(settings, engine, lib, rb)) as mac:
            health = (await mac.get("/v1/health")).json()
            assert health["builder"] == "remote"
            assert health["builder_detail"] == {"host": "win:8787", "methods": ["accurate", "fast"]}
            r = await mac.post("/v1/voices/build", data={**FORM, "method": "fast"}, files=_files())
            assert r.status_code == 202 and r.json()["builder"] == "remote:win:8787"
            done = await _wait(mac, r.json()["id"])
            assert done["state"] == "succeeded" and done["remote_id"] is not None
            voice = (await mac.get(f"/v1/voices/{done['voice_id']}")).json()
            assert voice["build"]["builder"] == "remote:win:8787"
            assert voice["build"]["method"] == "fast"
            bad = await mac.post("/v1/voices/build", data={**FORM, "consent": "no"}, files=_files())
            assert bad.status_code == 400 and bad.json()["error"]["code"] == "consent_required"
    finally:
        await rb.close()
        await http.aclose()
