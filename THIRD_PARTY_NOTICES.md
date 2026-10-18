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

## Acknowledgements and related work (not dependencies)

- [Supertone](https://github.com/supertone-inc) for Supertonic 3 and the `supertonic` package.
- [supertonic.embed](https://github.com/kdrkdrkdr/supertonic.embed) (MIT), the voice
  optimisation approach planned for Plan 2.
