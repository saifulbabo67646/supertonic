"""The voice-building worker: ``python -m supertonic_server.builder.worker``.

Runs one extraction in its own process, so PyTorch and CUDA never enter the server
process and a crash or out-of-memory error ends only this job. It writes one JSON object
per line to stdout:

- ``{"type": "progress", ...Progress}`` while working,
- then exactly one of ``{"type": "done", "report": {...}}`` (exit code 0) or
  ``{"type": "error", "code": ..., "message": ...}`` (exit code 1), with ``code`` one of
  ``cuda_unavailable``, ``out_of_memory``, ``extract_failed``, ``missing_dependencies``,
  ``nothing_to_save``, ``bad_arguments``.

Logs go to stderr. Creating the ``--stop-file`` asks the extractor to stop optimising and
save the best style so far. ``--self-test`` prints a single ``probe`` line describing torch,
CUDA and the methods whose dependencies import, then exits. ``SUPERTONIC_BUILDER_FAKE=1``
swaps in :mod:`.extract.fake` (and a fake probe) for tests.
"""

from __future__ import annotations

import argparse
import importlib
import json
import logging
import os
import sys
from contextlib import redirect_stdout, suppress
from dataclasses import asdict
from pathlib import Path
from typing import Any, NoReturn, Protocol, TextIO

from supertonic_server.builder.extract.base import (
    NothingToSaveError,
    ProgressCallback,
    Report,
    StopCheck,
    StyleJson,
    progress,
)
from supertonic_server.builder.models import BUILD_METHODS, BuildMethod, Progress

logger = logging.getLogger("supertonic_server.builder.worker")

FAKE_ENV = "SUPERTONIC_BUILDER_FAKE"
# Third-party modules each method needs beyond torch (import names).
METHOD_DEPS: dict[BuildMethod, tuple[str, ...]] = {
    "accurate": (
        "onnx",
        "onnxslim",
        "onnx2torch",
        "torchaudio",
        "soundfile",
        "librosa",
        "scipy",
        "speechbrain",
    ),
    "fast": ("onnx", "onnxslim", "onnx2torch", "soundfile", "librosa", "scipy", "transformers"),
}


class Extractor(Protocol):
    """The signature shared by the real and the fake ``extract_style``."""

    def __call__(
        self,
        method: BuildMethod,
        wav_path: Path,
        model_dir: Path,
        *,
        on_progress: ProgressCallback,
        should_stop: StopCheck,
        device: str = "cuda",
    ) -> tuple[StyleJson, Report]: ...


class WorkerError(Exception):
    """A failure with a protocol error code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class _Parser(argparse.ArgumentParser):
    """Argument errors become a ``bad_arguments`` protocol error instead of exit 2."""

    def error(self, message: str) -> NoReturn:
        raise WorkerError("bad_arguments", message)


# Where protocol lines go. ``main`` points it at stdout; the ``__main__`` entry hands it a
# private duplicate of fd 1 and sends fd 1 itself to stderr, so stray prints from
# libraries (Python or native) cannot corrupt the protocol.
_out: TextIO = sys.stdout


def _emit(obj: dict[str, Any]) -> None:
    _out.write(json.dumps(obj, ensure_ascii=False) + "\n")
    _out.flush()


def _emit_progress(p: Progress) -> None:
    _emit({"type": "progress", **asdict(p)})


def _fake() -> bool:
    return os.environ.get(FAKE_ENV) == "1"


def _import_torch() -> Any:
    try:
        return importlib.import_module("torch")
    except ImportError as exc:
        raise WorkerError(
            "missing_dependencies",
            f"torch is not importable ({exc}); install the builder extra: uv sync --extra builder",
        ) from exc


def _load_extractor(device: str) -> Extractor:
    """Return the extractor to run, after checking torch and the device."""
    if _fake():
        from supertonic_server.builder.extract.fake import extract_style as fake

        return fake
    torch = _import_torch()
    if device.startswith("cuda") and not torch.cuda.is_available():
        raise WorkerError(
            "cuda_unavailable", f"device {device!r} requested but CUDA is unavailable"
        )
    from supertonic_server.builder.extract import extract_style

    return extract_style


def _error_for(exc: BaseException) -> WorkerError:
    """Map an extractor exception to a protocol error."""
    if isinstance(exc, WorkerError):
        return exc
    message = f"{type(exc).__name__}: {exc}".strip()
    if isinstance(exc, NothingToSaveError):
        return WorkerError("nothing_to_save", str(exc))
    if type(exc).__name__ == "OutOfMemoryError" or "out of memory" in str(exc).lower():
        return WorkerError("out_of_memory", message)
    if isinstance(exc, ImportError):
        return WorkerError("missing_dependencies", message)
    return WorkerError("extract_failed", message)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    """Write ``payload`` atomically (temp file then rename)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(payload), encoding="utf-8")
    os.replace(tmp, path)


def _probe() -> dict[str, Any]:
    """Describe what this machine can build (raises ``WorkerError`` without torch)."""
    if _fake():
        return {
            "type": "probe",
            "torch": "fake",
            "cuda": True,
            "device": "fake",
            "vram_mb": 0,
            "methods": list(BUILD_METHODS),
        }
    torch = _import_torch()
    cuda = bool(torch.cuda.is_available())
    device, vram_mb = None, 0
    if cuda:
        props = torch.cuda.get_device_properties(0)
        device, vram_mb = str(props.name), int(props.total_memory // 2**20)
    methods = [m for m in BUILD_METHODS if _importable(METHOD_DEPS[m])]
    return {
        "type": "probe",
        "torch": str(torch.__version__),
        "cuda": cuda,
        "device": device,
        "vram_mb": vram_mb,
        "methods": methods,
    }


def _importable(modules: tuple[str, ...]) -> bool:
    for name in modules:
        try:
            importlib.import_module(name)
        except Exception as exc:  # any import-time failure means the method cannot run
            logger.info("dependency %s unavailable: %s", name, exc)
            return False
    return True


def _parser() -> argparse.ArgumentParser:
    ap = _Parser(
        prog="python -m supertonic_server.builder.worker",
        description="Build one Supertonic 3 voice style; JSON lines on stdout.",
    )
    ap.add_argument("--self-test", action="store_true", help="print a probe line and exit")
    ap.add_argument("--method", choices=BUILD_METHODS)
    ap.add_argument("--wav", type=Path, help="prepared reference recording")
    ap.add_argument("--out", type=Path, help="where to write the style JSON")
    ap.add_argument("--report", type=Path, help="where to write the report JSON")
    ap.add_argument("--model-dir", type=Path, help="Supertonic 3 model directory")
    ap.add_argument("--stop-file", type=Path, help="create this file to finish early")
    ap.add_argument("--device", default="cuda")
    return ap


def _setup_io() -> None:
    for stream, errors in ((sys.stdout, "strict"), (sys.stderr, "backslashreplace")):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            # On Windows, when fd 1 has been pointed at a console stderr (worker run by
            # hand with stdout piped), reconfiguring sys.stdout raises EINVAL; the old
            # encoding is harmless there because nothing protocol-related uses it.
            with suppress(OSError):
                reconfigure(encoding="utf-8", errors=errors)
    if not logging.getLogger().handlers:
        logging.basicConfig(
            stream=sys.stderr, level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
        )


def _build(args: argparse.Namespace) -> None:
    stop_file: Path = args.stop_file
    extractor = _load_extractor(args.device)
    logger.info("building with %s from %s", args.method, args.wav)
    with redirect_stdout(sys.stderr):
        style, report = extractor(
            args.method,
            args.wav,
            args.model_dir,
            on_progress=_emit_progress,
            should_stop=stop_file.exists,
            device=args.device,
        )
    _emit_progress(progress("saving", "saving the style"))
    try:
        _write_json(args.out, style)
        _write_json(args.report, report)
    except BaseException:
        args.out.unlink(missing_ok=True)  # never leave a style without its report
        raise
    _emit({"type": "done", "report": report})


def main(argv: list[str] | None = None, out: TextIO | None = None) -> int:
    """Run the worker; returns the process exit code (0 only on ``done``).

    Args:
        argv: Command-line arguments (default ``sys.argv[1:]``).
        out: Stream for protocol lines (default ``sys.stdout``).
    """
    global _out
    _setup_io()
    _out = out if out is not None else sys.stdout
    ap = _parser()
    try:
        args = ap.parse_args(argv)
        if args.self_test:
            with redirect_stdout(sys.stderr):
                probe = _probe()
            _emit(probe)
            return 0
        required = ("method", "wav", "out", "report", "model_dir", "stop_file")
        missing = [f"--{name.replace('_', '-')}" for name in required if not getattr(args, name)]
        if missing:
            ap.error(f"missing required arguments: {', '.join(missing)}")
        _build(args)
        return 0
    except Exception as exc:
        err = _error_for(exc)
        if isinstance(exc, WorkerError | NothingToSaveError):
            logger.error("build failed: %s: %s", err.code, err.message)
        else:
            logger.exception("build failed: %s", err.code)
        _emit({"type": "error", "code": err.code, "message": err.message})
        return 1


def _cli() -> int:
    """Process entry: keep a private handle on stdout, then point fd 1 at stderr."""
    sys.stdout.flush()
    protocol = os.fdopen(os.dup(1), "w", encoding="utf-8", newline="\n")
    os.dup2(2, 1)
    try:
        return main(out=protocol)
    finally:
        protocol.close()


if __name__ == "__main__":
    sys.exit(_cli())
