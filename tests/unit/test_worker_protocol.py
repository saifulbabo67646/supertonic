"""The builder worker's JSON-lines protocol, driven through the fake extractor."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import fields
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest

from supertonic_server.builder import Progress
from supertonic_server.builder import worker as worker_mod
from supertonic_server.builder.extract import extract_style
from supertonic_server.builder.extract.base import NothingToSaveError
from supertonic_server.voices.validation import validate_style

PROGRESS_KEYS = {f.name for f in fields(Progress)}
REPORT_KEYS = {
    "method",
    "preset_start",
    "preset_distance",
    "loss",
    "steps",
    "duration_status",
    "rate_ref",
    "rate_final",
    "stopped_early",
}

# Runs the worker in a fresh interpreter where ``import torch`` fails (or is faked), so the
# result does not depend on whether this environment has the builder extra installed.
NO_TORCH = "import sys; sys.modules['torch'] = None\n"
FAKE_TORCH_NO_CUDA = (
    "import sys, types\n"
    "torch = types.ModuleType('torch')\n"
    "torch.__version__ = '0.0-fake'\n"
    "torch.cuda = types.SimpleNamespace(is_available=lambda: False)\n"
    "sys.modules['torch'] = torch\n"
)
NOISY_FAKE = (
    "import os, sys\n"
    "import supertonic_server.builder.extract.fake as fake\n"
    "real = fake.extract_style\n"
    "def noisy(*a, **k):\n"
    "    print('python noise')\n"
    "    os.write(1, b'native noise\\n')\n"
    "    return real(*a, **k)\n"
    "fake.extract_style = noisy\n"
)
RUN_MAIN = "from supertonic_server.builder.worker import _cli\nsys.exit(_cli())\n"


def _env(fake: bool) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("SUPERTONIC_")}
    env["PYTHONUTF8"] = "1"
    if fake:
        env["SUPERTONIC_BUILDER_FAKE"] = "1"
    return env


def _run(
    args: list[str], *, fake: bool = True, shim: str | None = None
) -> tuple[int, list[dict[str, Any]], str]:
    """Run the worker; return (exit code, parsed stdout lines, stderr)."""
    if shim is None:
        cmd = [sys.executable, "-m", "supertonic_server.builder.worker", *args]
    else:
        cmd = [sys.executable, "-c", shim + RUN_MAIN, *args]
    proc = subprocess.run(
        cmd, capture_output=True, text=True, encoding="utf-8", env=_env(fake), timeout=120
    )
    lines = [json.loads(line) for line in proc.stdout.splitlines() if line.strip()]
    return proc.returncode, lines, proc.stderr


@pytest.fixture
def job(tmp_path: Path) -> dict[str, Path]:
    wav = tmp_path / "ref.wav"
    wav.write_bytes(b"RIFF fake")
    model = tmp_path / "model"
    model.mkdir()
    return {
        "wav": wav,
        "out": tmp_path / "out" / "style.json",
        "report": tmp_path / "out" / "report.json",
        "model": model,
        "stop": tmp_path / "STOP",
    }


def _args(job: dict[str, Path], method: str) -> list[str]:
    return [
        "--method",
        method,
        "--wav",
        str(job["wav"]),
        "--out",
        str(job["out"]),
        "--report",
        str(job["report"]),
        "--model-dir",
        str(job["model"]),
        "--stop-file",
        str(job["stop"]),
    ]


@pytest.mark.parametrize("method", ["accurate", "fast"])
def test_fake_build_emits_progress_then_done(job: dict[str, Path], method: str) -> None:
    code, lines, _ = _run(_args(job, method))
    assert code == 0
    progress = [line for line in lines if line["type"] == "progress"]
    assert [p["stage"] for p in progress[:3]] == ["loading", "timbre", "duration"]
    assert progress[-1]["stage"] == "saving"
    for p in progress:
        assert set(p) == PROGRESS_KEYS | {"type"}
    done = lines[-1]
    assert done["type"] == "done"
    assert set(done["report"]) >= REPORT_KEYS
    assert done["report"]["method"] == method
    assert done["report"]["stopped_early"] is False
    style = json.loads(job["out"].read_text(encoding="utf-8"))
    validate_style(style)
    assert json.loads(job["report"].read_text(encoding="utf-8")) == done["report"]


def test_fake_style_rows_are_unit_vectors(job: dict[str, Path]) -> None:
    code, _, _ = _run(_args(job, "fast"))
    assert code == 0
    style = json.loads(job["out"].read_text(encoding="utf-8"))
    for key in ("style_ttl", "style_dp"):
        norms = np.linalg.norm(np.asarray(style[key]["data"], dtype=np.float32), axis=-1)
        assert np.allclose(norms, 1.0, atol=1e-5)


def test_stop_file_ends_after_current_event(job: dict[str, Path]) -> None:
    job["stop"].write_text("", encoding="utf-8")
    code, lines, _ = _run(_args(job, "fast"))
    assert code == 0
    fake_events = [p for p in lines if p["type"] == "progress" and p["stage"] != "saving"]
    assert len(fake_events) == 1
    assert lines[-1]["type"] == "done"
    assert lines[-1]["report"]["stopped_early"] is True
    validate_style(json.loads(job["out"].read_text(encoding="utf-8")))


def test_extract_failure_is_an_error_line(job: dict[str, Path]) -> None:
    job["wav"].unlink()
    code, lines, _ = _run(_args(job, "fast"))
    assert code != 0
    assert lines[-1]["type"] == "error"
    assert lines[-1]["code"] == "extract_failed"
    assert lines[-1]["message"]
    assert not job["out"].exists()
    assert not job["report"].exists()


def test_every_stdout_line_is_json(job: dict[str, Path]) -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "supertonic_server.builder.worker", *_args(job, "fast")],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=_env(True),
        timeout=120,
    )
    for line in proc.stdout.splitlines():
        assert isinstance(json.loads(line), dict)


def test_library_output_on_stdout_goes_to_stderr(job: dict[str, Path]) -> None:
    code, lines, stderr = _run(_args(job, "fast"), shim=NOISY_FAKE)
    assert code == 0
    assert lines[-1]["type"] == "done"
    assert "python noise" in stderr
    assert "native noise" in stderr


def test_missing_torch_is_missing_dependencies(job: dict[str, Path]) -> None:
    code, lines, _ = _run(_args(job, "fast"), fake=False, shim=NO_TORCH)
    assert code != 0
    assert lines == [
        {"type": "error", "code": "missing_dependencies", "message": lines[0]["message"]}
    ]
    assert "torch" in lines[0]["message"]


def test_no_cuda_is_cuda_unavailable(job: dict[str, Path]) -> None:
    code, lines, _ = _run(_args(job, "fast"), fake=False, shim=FAKE_TORCH_NO_CUDA)
    assert code != 0
    assert lines[-1]["type"] == "error"
    assert lines[-1]["code"] == "cuda_unavailable"


def test_self_test_without_torch_prints_missing_dependencies() -> None:
    code, lines, _ = _run(["--self-test"], fake=False, shim=NO_TORCH)
    assert code != 0
    assert len(lines) == 1
    assert lines[0]["type"] == "error"
    assert lines[0]["code"] == "missing_dependencies"


def test_self_test_without_cuda_reports_no_device() -> None:
    code, lines, _ = _run(["--self-test"], fake=False, shim=FAKE_TORCH_NO_CUDA)
    assert code == 0
    (probe,) = lines
    assert probe["type"] == "probe"
    assert probe["torch"] == "0.0-fake"
    assert probe["cuda"] is False
    assert probe["device"] is None
    assert probe["vram_mb"] == 0
    assert set(probe["methods"]) <= {"accurate", "fast"}


def test_fake_self_test_probe_lists_both_methods() -> None:
    code, lines, _ = _run(["--self-test"])
    assert code == 0
    (probe,) = lines
    assert probe["type"] == "probe"
    assert probe["cuda"] is True
    assert probe["methods"] == ["accurate", "fast"]
    assert isinstance(probe["vram_mb"], int)


def test_missing_required_args_is_bad_arguments() -> None:
    code, lines, _ = _run(["--method", "fast"])
    assert code != 0
    assert len(lines) == 1
    assert lines[0]["type"] == "error"
    assert lines[0]["code"] == "bad_arguments"
    assert "--wav" in lines[0]["message"]


def test_unknown_method_is_bad_arguments(job: dict[str, Path]) -> None:
    code, lines, _ = _run(_args(job, "slow"))
    assert code != 0
    assert lines == [{"type": "error", "code": "bad_arguments", "message": lines[0]["message"]}]
    assert "slow" in lines[0]["message"]
    assert not job["out"].exists()


def test_server_app_does_not_import_builder_deps() -> None:
    heavy = ("torch", "torchaudio", "transformers", "speechbrain", "onnx2torch")
    probe = (
        "import sys, json\n"
        "import supertonic_server.api.app\n"
        "import supertonic_server.builder\n"
        f"print(json.dumps([m for m in {heavy!r} if m in sys.modules]))\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", probe],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=_env(False),
        timeout=120,
    )
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout.strip().splitlines()[-1]) == []


class OutOfMemoryError(RuntimeError):
    """Named like ``torch.cuda.OutOfMemoryError`` so the worker maps it without torch."""


@pytest.mark.parametrize(
    ("exc", "code"),
    [
        (NothingToSaveError("stopped before any style existed"), "nothing_to_save"),
        (OutOfMemoryError("CUDA out of memory. Tried to allocate 2 GiB"), "out_of_memory"),
        (ModuleNotFoundError("No module named 'transformers'"), "missing_dependencies"),
        (RuntimeError("boom"), "extract_failed"),
    ],
)
def test_extractor_exceptions_map_to_error_codes(
    job: dict[str, Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    exc: Exception,
    code: str,
) -> None:
    def boom(*args: Any, **kwargs: Any) -> Any:
        raise exc

    monkeypatch.setattr(worker_mod, "_load_extractor", lambda device: boom)
    rc = worker_mod.main(_args(job, "fast"))
    assert rc != 0
    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert lines[-1]["type"] == "error"
    assert lines[-1]["code"] == code
    assert not job["out"].exists()


@pytest.mark.parametrize("method", ["accurate", "fast"])
def test_dispatcher_runs_the_method_module(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, method: str
) -> None:
    """Each method is imported lazily from its own subpackage (stubbed: no torch needed)."""
    calls: list[dict[str, Any]] = []

    def fake(wav_path: Path, model_dir: Path, **kwargs: Any) -> tuple[dict[str, Any], dict]:
        calls.append({"wav": wav_path, "model": model_dir, **kwargs})
        return {"style": method}, {"method": method}

    module = SimpleNamespace(extract_style=fake)
    monkeypatch.setitem(sys.modules, f"supertonic_server.builder.extract.{method}.extract", module)
    style, report = extract_style(
        method,  # type: ignore[arg-type]
        tmp_path / "ref.wav",
        tmp_path,
        on_progress=lambda p: None,
        should_stop=lambda: False,
        device="cpu",
    )
    assert (style, report) == ({"style": method}, {"method": method})
    assert calls[0]["wav"] == tmp_path / "ref.wav" and calls[0]["device"] == "cpu"


def test_dispatcher_rejects_unknown_method(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="method"):
        extract_style(
            "slow",  # type: ignore[arg-type]
            tmp_path / "ref.wav",
            tmp_path,
            on_progress=lambda p: None,
            should_stop=lambda: False,
        )


def test_setup_io_tolerates_a_stream_that_cannot_be_reconfigured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Windows: after fd 1 is pointed at a console stderr, sys.stdout.reconfigure raises
    # OSError(22); the self-test run by hand from a console must still print its probe.
    calls: list[str] = []

    def broken(**kwargs: Any) -> None:
        calls.append("stdout")
        raise OSError(22, "Invalid argument")

    def ok(**kwargs: Any) -> None:
        calls.append("stderr")

    monkeypatch.setattr(sys, "stdout", SimpleNamespace(reconfigure=broken))
    monkeypatch.setattr(sys, "stderr", SimpleNamespace(reconfigure=ok, write=lambda s: None))
    worker_mod._setup_io()
    assert calls == ["stdout", "stderr"]
