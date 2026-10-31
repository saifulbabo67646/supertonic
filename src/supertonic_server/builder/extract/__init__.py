"""Style extractors: turn a prepared reference recording into a Supertonic 3 voice style.

Each method lives in its own subpackage and imports PyTorch, so it is imported only when
:func:`extract_style` runs it, inside the builder worker process. Importing this package
is cheap and never imports torch.

Vendored upstreams (MIT, adapted; see the file headers and ``THIRD_PARTY_NOTICES.md``):

- ``fast`` and the shared duration inversion: supertonic.embed by Gyeongmin Kim,
  :data:`EMBED_UPSTREAM` at :data:`EMBED_SHA`.
- ``accurate`` and the ONNX-to-torch fixes in ``common.frozen_tts``: supertonic3-voice-clone
  by Saurabh Verma, :data:`VC3_UPSTREAM` at :data:`VC3_SHA`.
"""

from __future__ import annotations

from pathlib import Path

from supertonic_server.builder.extract.base import (
    NothingToSaveError,
    ProgressCallback,
    Report,
    StopCheck,
    StyleJson,
)
from supertonic_server.builder.models import BUILD_METHODS, BuildMethod

EMBED_UPSTREAM = "https://github.com/kdrkdrkdr/supertonic.embed"
EMBED_SHA = "6c38a94af2c429d7f4098708686af80d23ccadc0"
VC3_UPSTREAM = "https://github.com/saurabhv749/supertonic3-voice-clone"
VC3_SHA = "765ce5e27daa8d30937e2d0d8f9730280add5748"

__all__ = ["NothingToSaveError", "extract_style"]


def extract_style(
    method: BuildMethod,
    wav_path: Path,
    model_dir: Path,
    *,
    on_progress: ProgressCallback,
    should_stop: StopCheck,
    device: str = "cuda",
) -> tuple[StyleJson, Report]:
    """Build a voice style from ``wav_path`` with ``method``.

    Args:
        method: ``"accurate"`` or ``"fast"``.
        wav_path: The prepared reference recording (mono WAV).
        model_dir: The Supertonic 3 directory (``onnx/`` and ``voice_styles/``).
        on_progress: Called with each progress snapshot.
        should_stop: Polled every optimisation step; when it returns true the extractor
            ends the timbre stage with the best style so far, still matches the rhythm,
            and returns it with ``stopped_early: true``. A stop that first appears during
            the rhythm stage ends that stage too.
        device: Torch device, e.g. ``"cuda"``.

    Returns:
        ``(style_json, report)``: the style in the shipped JSON format and a report with
        ``method, preset_start, preset_distance, loss, steps, duration_status, rate_ref,
        rate_final, stopped_early, pitch_reference_hz, pitch_voice_hz, pitch_match``
        (``accurate`` adds ``similarity`` and ``best_step``).

    Raises:
        ValueError: ``method`` is not a known build method.
        NothingToSaveError: stopped before any style existed.
    """
    if method not in BUILD_METHODS:
        raise ValueError(f"unknown build method {method!r}")
    if method == "accurate":
        from supertonic_server.builder.extract.accurate.extract import extract_style as accurate

        return accurate(
            wav_path, model_dir, on_progress=on_progress, should_stop=should_stop, device=device
        )
    from supertonic_server.builder.extract.fast.extract import extract_style as fast

    return fast(
        wav_path, model_dir, on_progress=on_progress, should_stop=should_stop, device=device
    )
