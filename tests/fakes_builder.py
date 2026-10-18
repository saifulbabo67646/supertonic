"""A scripted stand-in for ``python -m supertonic_server.builder.worker`` (run as a script).

``JobManager(worker_cmd=[sys.executable, FAKE_WORKER])`` runs this file with the worker's
arguments. Behaviour comes from the environment:

- ``FAKE_BUILDER_DIR``: control directory. Run ``n`` (0-based, counted per directory) writes
  ``run-<n>.json`` (``pid``, ``child_pid``, ``argv``) before doing anything else.
- ``FAKE_BUILDER_MODES``: comma-separated mode per run (the last one repeats; default ``ok``):

  - ``ok``: two progress events, then ``done``.
  - ``noisy``: like ``ok`` with a non-JSON line on stdout first.
  - ``flood``: like ``noisy`` plus ~1 MB of progress lines and stderr (fills any pipe buffer).
  - ``gate``: ``loading`` and one ``timbre`` step, then waits for ``<dir>/go`` or the stop
    file, then ``done`` (``stopped_early`` true when the stop file ended the wait).
  - ``hang``: starts a sleeping child process (the "tree"), then sleeps, ignoring the stop file.
  - ``crash``: a progress event and a traceback on stderr, then exit code 3, no terminal event.
  - ``error:<code>``: an error event with ``code`` (exit code 1).
  - ``slow``: every stage, with ``FAKE_BUILDER_STEPS`` (default 30) ``timbre`` steps of
    ``FAKE_BUILDER_STEP_S`` seconds (default 0.5) each; the stop file ends the steps early.
    For trying the web UI by hand (progress, ETA, Finish now, Cancel).
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

FAKE_WORKER = str(Path(__file__).resolve())


def _emit(obj: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def _progress(
    stage: str, message: str, step: int | None = None, total: int = 3, loss: float = 0.5
) -> None:
    at = datetime.now(UTC).isoformat()
    _emit(
        {
            "type": "progress",
            "stage": stage,
            "step": step,
            "total": total if step is not None else None,
            "loss": loss if step is not None else None,
            "message": message,
            "at": at,
        }
    )


def _slow(args: argparse.Namespace) -> int:
    total = int(os.environ.get("FAKE_BUILDER_STEPS", "30"))
    delay = float(os.environ.get("FAKE_BUILDER_STEP_S", "0.5"))
    for stage in ("loading", "preset"):
        _progress(stage, f"fake: {stage}")
        time.sleep(delay * 2)
    step = 0
    while step < total and not args.stop_file.exists():
        step += 1
        _progress("timbre", f"fake: step {step}", step=step, total=total, loss=0.5 / step)
        time.sleep(delay)
    stopped = args.stop_file.exists()
    for stage in ("duration", "saving"):
        _progress(stage, f"fake: {stage}")
        time.sleep(delay * 2)
    return _done(args, stopped, steps=step, loss=0.5 / max(step, 1))


def _done(
    args: argparse.Namespace, stopped: bool, steps: int | None = None, loss: float = 0.25
) -> int:
    from supertonic_server.builder.extract.fake import make_style

    report = {
        "method": args.method,
        "preset_start": "F1",
        "preset_distance": 0.5,
        "loss": loss,
        "steps": steps if steps is not None else (1 if stopped else 3),
        "duration_status": "converged",
        "rate_ref": 3.0,
        "rate_final": 3.0,
        "stopped_early": stopped,
    }
    if steps is not None and args.method == "accurate":
        report["similarity"] = round(1 - loss, 4)
    args.out.write_text(json.dumps(make_style()), encoding="utf-8")
    args.report.write_text(json.dumps(report), encoding="utf-8")
    _emit({"type": "done", "report": report})
    return 0


def main() -> int:
    """Run one scripted build."""
    ap = argparse.ArgumentParser()
    for name in ("--method", "--device"):
        ap.add_argument(name)
    for name in ("--wav", "--out", "--report", "--model-dir", "--stop-file"):
        ap.add_argument(name, type=Path)
    args = ap.parse_args()
    control = Path(os.environ["FAKE_BUILDER_DIR"])
    modes = os.environ.get("FAKE_BUILDER_MODES", "ok").split(",")
    n = len(list(control.glob("run-*.json")))
    mode = modes[min(n, len(modes) - 1)]
    child = None
    if mode == "hang":
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    info = {"pid": os.getpid(), "child_pid": child.pid if child else None, "argv": sys.argv[1:]}
    tmp = control / f"run-{n}.tmp"
    tmp.write_text(json.dumps(info), encoding="utf-8")
    os.replace(tmp, control / f"run-{n}.json")
    if mode == "hang":
        time.sleep(60)
        return 0
    if mode == "crash":
        _progress("loading", "fake: loading")
        sys.stderr.write("Traceback (most recent call last):\nRuntimeError: kaboom\n")
        sys.stderr.flush()
        return 3
    if mode.startswith("error:"):
        sys.stderr.write("about to fail\n")
        _emit(
            {"type": "error", "code": mode.split(":", 1)[1], "message": f"fake failure: {mode[6:]}"}
        )
        return 1
    if mode in ("noisy", "flood"):
        print("this is not json", flush=True)
    if mode == "flood":
        for i in range(2500):
            _progress("timbre", "fake: flooding " + "x" * 100, step=i)
            sys.stderr.write(f"log line {i} " + "y" * 200 + "\n")
    if mode == "slow":
        return _slow(args)
    _progress("loading", "fake: loading")
    if mode == "gate":
        _progress("timbre", "fake: timbre", step=1)
        while not (control / "go").exists() and not args.stop_file.exists():
            time.sleep(0.01)
        return _done(args, stopped=args.stop_file.exists())
    _progress("timbre", "fake: timbre", step=1)
    return _done(args, stopped=False)


if __name__ == "__main__":
    sys.exit(main())
