"""Download every model a voice build needs.

Run as ``python -m supertonic_server.builder.extract.prefetch``. The setup scripts run it
once so the first build does not stall on downloads: the Supertonic 3 model (the same
cache the server uses), WavLM-Large (``fast``) and the ECAPA speaker encoder
(``accurate``). Each model is loaded once on the CPU, which also proves the copy on disk
is usable. Prints one ``ok <name> <location>`` line per model; on the first failure prints
``error <name>: <reason>`` to stderr and exits 1. Needs the builder extra.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from pathlib import Path


def _supertonic(model_dir: Path | None) -> str:
    import supertonic

    tts = supertonic.TTS(model="supertonic-3", model_dir=model_dir, auto_download=True)
    return str(tts.model_dir)


def _wavlm(model_dir: Path | None) -> str:
    import torch

    from supertonic_server.builder.extract.fast.config import WAVLM_REPO
    from supertonic_server.builder.extract.fast.wavlm_loss import load_wavlm

    load_wavlm(torch.device("cpu"))
    return WAVLM_REPO


def _ecapa(model_dir: Path | None) -> str:
    import torch

    from supertonic_server.builder.extract.accurate.speaker_loss import ecapa_savedir, load_ecapa

    load_ecapa(torch.device("cpu"))
    return str(ecapa_savedir())


STEPS: tuple[tuple[str, Callable[[Path | None], str]], ...] = (
    ("supertonic-3", _supertonic),
    ("wavlm-large", _wavlm),
    ("ecapa", _ecapa),
)


def main(argv: list[str] | None = None) -> int:
    """Fetch each model in turn; returns the process exit code."""
    ap = argparse.ArgumentParser(
        prog="python -m supertonic_server.builder.extract.prefetch",
        description="Download the models a voice build needs.",
    )
    ap.add_argument("--model-dir", type=Path, help="Supertonic 3 directory (default: HF cache)")
    args = ap.parse_args(argv)
    for name, fetch in STEPS:
        print(f"fetching {name} ...", flush=True)
        try:
            where = fetch(args.model_dir)
        except Exception as exc:  # report which model failed, not a traceback
            print(f"error {name}: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
            return 1
        print(f"ok {name} {where}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
