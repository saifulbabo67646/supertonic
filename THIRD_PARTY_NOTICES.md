# Third-party notices

Supertonic Server's own code is MIT licensed (see `LICENSE`). It depends on, downloads or
bundles the following. Licence names were read from the installed package metadata
(`.venv/.../*.dist-info/METADATA`) at the versions pinned in `uv.lock`.

## Model weights

- **Supertonic 3** (`Supertone/supertonic-3` on Hugging Face), downloaded on first run and
  not redistributed in this repository. Licensed under **OpenRAIL-M** by Supertone Inc.
  The licence carries use restrictions that apply to the model, to audio generated with
  it and to voices derived from it. Read it before use:
  <https://huggingface.co/Supertone/supertonic-3>

## Python packages

| Package | Version | Licence |
|---|---|---|
| [supertonic](https://pypi.org/project/supertonic/) (Supertone) | 1.3.1 | MIT |
| [onnxruntime](https://onnxruntime.ai) (Microsoft, dependency of supertonic) | 1.31.0 | MIT |
| [mcp](https://pypi.org/project/mcp/) (Model Context Protocol) | 2.3.0 | MIT |
| [soxr](https://pypi.org/project/soxr/) (python-soxr, wraps libsoxr) | 1.1.0 | LGPL-2.1-or-later |
| [imageio-ffmpeg](https://github.com/imageio/imageio-ffmpeg) | 0.6.0 | BSD-2-Clause (wrapper) |
| FastAPI, uvicorn, pydantic, pydantic-settings, numpy, httpx, python-multipart | see `uv.lock` | MIT / BSD-3-Clause |

`soxr` is dynamically linked as a separate wheel and used unmodified; you may replace it
with another build.

## ffmpeg (via imageio-ffmpeg)

Audio encoding to mp3, opus, aac and flac runs the **ffmpeg** binary that `imageio-ffmpeg`
ships in its platform wheel. imageio-ffmpeg itself is BSD-2-Clause, but the bundled ffmpeg
is a separate program built with `--enable-gpl` (libx264, libx265, libmp3lame and others),
so that binary is distributed under the **GNU GPL**, with parts under the LGPL. This project
runs it as a separate process and does not link to it. Source and licence information:
<https://ffmpeg.org/legal.html>. If you redistribute a bundle that includes it, you must
comply with the GPL for that binary; you can instead point to a system ffmpeg built under
the licence you need.

## Vendored code (voice builder)

- **supertonic.embed** by Gyeongmin Kim, MIT License,
  <https://github.com/kdrkdrkdr/supertonic.embed> at
  `6c38a94af2c429d7f4098708686af80d23ccadc0`. Adapted copies live in
  `src/supertonic_server/builder/extract/common/` (frozen TTS, style file, duration
  inversion) and `src/supertonic_server/builder/extract/fast/` (the `fast` build method);
  each file's header says what changed. Full licence text:
  `src/supertonic_server/builder/extract/LICENSE-supertonic-embed`. Upstream's
  TLS-verification bypass was not vendored.
- **supertonic3-voice-clone** by Saurabh Verma, MIT License,
  <https://github.com/saurabhv749/supertonic3-voice-clone> at
  `765ce5e27daa8d30937e2d0d8f9730280add5748` (its `train_style.py` is a modified version
  of Gyeongmin Kim's `optimize_style.py`, MIT): the `accurate` build method in
  `src/supertonic_server/builder/extract/accurate/` (speaker-similarity loss, the
  optimisation loop and its settings, and the 16 training sentences from
  `configs/utterances.py`, verbatim) and the ONNX-to-PyTorch loading fixes (Clip inputs,
  in-memory shape inference) in `builder/extract/common/frozen_tts.py`. Each file's header
  says what changed. Full licence text and upstream's NOTICE:
  `src/supertonic_server/builder/extract/LICENSE-supertonic3-voice-clone` and
  `NOTICE-supertonic3-voice-clone`. Upstream's TLS-verification bypass and its removal of
  certificate environment variables were not vendored.

## Builder extra (optional, `uv sync --extra builder`)

Installed only for local voice building and imported only by the builder worker process:
PyTorch, torchaudio and torchvision (BSD-3-Clause; CUDA 12.6 wheels from the PyTorch
index on Windows and Linux, which bundle NVIDIA CUDA runtime libraries under NVIDIA's
licence), onnx (Apache-2.0), onnx2torch (Apache-2.0), onnxslim (MIT), librosa (ISC), SciPy
(BSD-3-Clause), soundfile (BSD-3-Clause, wraps libsndfile, LGPL-2.1), Hugging Face
transformers (Apache-2.0) and SpeechBrain (Apache-2.0).

Model weights downloaded on first build, not redistributed here:

- **WavLM-Large** (`microsoft/wavlm-large`, ~1.2 GB), used by the `fast` method. Licence:
  see <https://huggingface.co/microsoft/wavlm-large> (the WavLM code is MIT).
- **ECAPA-TDNN speaker encoder** (`speechbrain/spkrec-ecapa-voxceleb`, ~80 MB), trained by
  SpeechBrain on VoxCeleb, used by the `accurate` method through the **SpeechBrain**
  toolkit (Apache-2.0, <https://speechbrain.github.io/>). The model is published under
  Apache-2.0: <https://huggingface.co/speechbrain/spkrec-ecapa-voxceleb>. It is fetched
  into `<Hugging Face hub cache>/supertonic-ecapa` (e.g.
  `~/.cache/huggingface/hub/supertonic-ecapa`) as plain copies, not symlinks.

## Acknowledgements and related work (not dependencies)

- [Supertone](https://github.com/supertone-inc) for Supertonic 3 and the `supertonic` package.
