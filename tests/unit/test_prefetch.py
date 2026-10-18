"""The model prefetch used by the setup scripts (loaders faked; nothing is downloaded)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from supertonic_server.builder.extract import prefetch


def _fake_steps(calls: list[tuple[str, Path | None]], fail: str | None = None) -> tuple:
    def make(name: str):  # type: ignore[no-untyped-def]
        def fetch(model_dir: Path | None) -> str:
            calls.append((name, model_dir))
            if name == fail:
                raise OSError("no network")
            return f"/cache/{name}"

        return fetch

    return tuple((name, make(name)) for name in ("supertonic-3", "wavlm-large", "ecapa"))


def test_prefetch_fetches_every_model_in_order(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    calls: list[tuple[str, Path | None]] = []
    monkeypatch.setattr(prefetch, "STEPS", _fake_steps(calls))
    assert prefetch.main(["--model-dir", str(tmp_path)]) == 0
    assert [c[0] for c in calls] == ["supertonic-3", "wavlm-large", "ecapa"]
    assert all(c[1] == tmp_path for c in calls)
    out = capsys.readouterr().out
    assert "ok supertonic-3 /cache/supertonic-3" in out
    assert "ok ecapa /cache/ecapa" in out


def test_prefetch_stops_at_first_failure_with_its_name(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    calls: list[tuple[str, Path | None]] = []
    monkeypatch.setattr(prefetch, "STEPS", _fake_steps(calls, fail="wavlm-large"))
    assert prefetch.main([]) == 1
    assert [c[0] for c in calls] == ["supertonic-3", "wavlm-large"]
    err = capsys.readouterr().err
    assert "error wavlm-large: OSError: no network" in err


def test_prefetch_module_imports_without_torch() -> None:
    # The real steps import torch lazily, so the module (and --help) work without the extra.
    assert [name for name, _ in prefetch.STEPS] == ["supertonic-3", "wavlm-large", "ecapa"]
    # In a fresh interpreter, since this one may already hold torch from other tests.
    code = (
        "import sys\n"
        "import supertonic_server.builder.extract.prefetch\n"
        "assert 'torch' not in sys.modules, 'prefetch imported torch'\n"
    )
    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
