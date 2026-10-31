# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- Named built-in voices: `F1` to `F5` are Mia, Nora, Lena, Sofia and Yuna, `M1` to `M5` are
  Hugo, Diego, Ravi, Felix and Omar, each with a one-line description based on measured
  pitch and pace (`docs/voices.md`, `scripts/describe_presets.py`). A name works anywhere
  an id does (REST, OpenAI endpoint, WebSocket, MCP, web UI), in any capitalisation; ids
  keep working and responses still return the id. Custom voices cannot take a built-in
  name or id (`409 voice_name_taken`). The web UI shows "Mia · F1" labels and the
  selected voice's description.
- One-click launchers for people who do not use a terminal: `Start Supertonic.command`
  (macOS), `Start Supertonic.bat` (Windows) and `start-supertonic.sh` (Linux) install uv
  if needed, install the dependencies (with the voice builder on NVIDIA machines, falling
  back to a plain install if that fails), start the server and open the Studio. New
  `supertonic-server launch` (reuse a running server, else pick a free port from 8787 to
  8799, start, open the browser; `--no-open`) and `serve --open`. The Connect page says
  how to stop the server; `docs/troubleshooting.md` covers the first start, macOS and
  Windows warnings, ports, the builder install and where data lives.
- `supertonic-server check`: a smoke test of a running server (health, a speech file and
  word timestamps) that prints `PASS` or the reason it failed, the same on every system.
  It asks for the voice by id (`F1`), so it also passes against an older server that an
  agent reuses.
- Setup by coding agents: `AGENTS.md` (prerequisites, exact commands for macOS, Windows
  and Linux, running in the background, verification, the voice builder, MCP, common
  failures and a definition of done), `CLAUDE.md` importing it, and `docs/agent-setup.md`
  with one copy-paste prompt and variations (GPU builder, forwarding from a Mac, MCP,
  replacing a hosted TTS provider in an app).
- `docs/getting-started.md`, a beginner's guide: download, double-click, a tour of the
  Studio, making your own voice, updating and uninstalling, and common questions.
- Community files for the public repository: a full Contributor Covenant 2.1, a security
  policy with supported versions and private reporting, GitHub issue forms, a pull request
  template, a docs index (`docs/README.md`), CodeQL scanning and weekly Dependabot updates.

### Changed

- The README is now a short product page with three ways to start (double-click, coding
  agent, developer); the detail moved to new pages `docs/configuration.md`, `docs/mcp.md`
  and `docs/remote-access.md`, and the realtime WebSocket events to `docs/api.md`.
  `docs/integrations.md` covers OpenAI-style apps and moving from hosted voice services.
- Package metadata: SPDX licence expression, authors, keywords, classifiers and project
  links; the version is defined once, in `supertonic_server.__version__`.
- CI runs lint and type checks once, the tests on Linux, macOS and Windows with Python
  3.11 to 3.13, and a package build check, on current GitHub Actions versions.
- CI installs Node 22 so the Studio's JavaScript tests always run there (they fail
  instead of being skipped when `CI` is set and Node is missing), and runs on `main` are
  no longer cancelled by later pushes. Dependabot leaves `torch`, `torchaudio` and
  `torchvision` alone (they are pinned together from the CUDA index); the large-file
  pre-commit check skips `docs/media/`.
- Internal: the voice builder's job runner moved to its own module (no behaviour change).
- `scripts/setup-builder.ps1` and `.sh` end with how to start the server; the LAN `.env`
  lines (`SUPERTONIC_HOST=0.0.0.0` and a key) are now clearly optional and come after the
  SSH-tunnel way, so nobody opens a builder to the network by copying them.

### Fixed

- Voice building chooses its start voice by pitch first, so a man's recording no longer
  becomes a woman's voice. Both methods measure the median pitch of the recording and of
  each built-in voice in the scan (shown as `F4: 0.3123 · 198 Hz`); only the built-in
  voices within about ±12% (log-distance 0.12) compete (the two nearest by pitch when none
  is), and the best judge score among them wins. The built voice counts as a pitch match
  within about ±22% (log-distance 0.2), measured as one median over the voiced frames of
  the first four sentences it speaks (one sentence alone is too noisy: 99 Hz for a 130 Hz
  speaker). The build report adds `pitch_reference_hz`, `pitch_voice_hz` and
  `pitch_match`, MCP `get_job` returns the new voice's `build` report, and the Studio
  warns when a finished voice sounds higher or lower than its recording.
- A custom voice can no longer take over a built-in name: lookups now try the exact id,
  then the built-in name, then the id in any capitalisation, then the custom voice name, so
  `"Mia"` always means `F1` (a voice saved earlier with the id `mia` still answers to
  exactly `mia`). A new voice called "Mia." gets the id `mia-2`, not `mia`. The Studio's
  `?voice=` link follows the same order.
- `.env` is read as UTF-8 with or without a byte-order mark, so a file saved from Windows
  PowerShell 5.1 no longer loses its first setting without a word. AGENTS.md shows how to
  write `.env` there (`Set-Content ... -Encoding ascii`) and the full background start
  line with a one-off variable.
- `supertonic-server launch --port <port>` uses only that port: it no longer reuses a
  server on a nearby port or moves to another free one. Without `--port` it still picks
  from 8787 to 8799.
- The macOS and Linux launchers run `scripts/launch.sh` with bash, so they still work if
  that file lost its executable mark.
- Studio: the Claude Code command on the Connect page is one line with `--scope user`, so
  it pastes into Windows PowerShell and cmd too; the Connect page also says how to stop a
  server started in the background. After a build, the reading-text picker goes back to
  English with its passage; failed and cancelled builds get their own heading; Likeness
  only shows during the timbre stage. The speed hint says the slider starts at 1.05.
  "Try a sample" keeps text you already typed. A full queue (`server_busy`) says
  Supertonic is busy, and other messages that merely contain "busy" are shown as they are.
- MCP `preview_voice` names its file after the voice's id, so asking for `"Mia"` saves
  `preview-F1-en-<time>.wav`, the same as `"F1"`.
- The docs say where the model is stored: `~/.cache/supertonic3`.
- Beginner docs: what to do when macOS shows no **Open Anyway** button, and the Windows
  firewall prompt (not expected with the default settings; click **Cancel**).
- `scripts/serve.sh` and `scripts/serve.ps1` no longer uninstall the voice builder extra
  (`uv sync --inexact`).
- CONTRIBUTING's start command (`uv run supertonic-server serve`).
- AGENTS.md: the Windows background start survives the end of the agent's command (also
  over SSH); step-by-step SSH tunnel for forwarding builds from a Mac; the builder setup
  can run before the first start.

## [0.1.0] - 2026-10-31

First public release.

### Added

- Project scaffold, settings and a startup safety check that refuses non-loopback binds
  or a public URL without an API key.
- Synthesis engine with a priority worker pool (realtime ahead of REST), bounded queue and
  sentence-level streaming.
- OpenAI-compatible `POST /v1/audio/speech` (mp3, opus, aac, flac, wav, pcm) with
  `language`, `total_steps` and `sample_rate` extensions, plus `/v1/models`,
  `/v1/languages` and `/v1/health`.
- Voice library with 10 presets, custom voice import (JSON or multipart), export, rename,
  delete and cached previews.
- `POST /v1/tts/timestamps` with estimated segment and word timings.
- Realtime TTS WebSocket with contexts, barge-in, partial-sentence flushing, backpressure and
  work caps; `SUPERTONIC_REALTIME_STEPS` (default 3).
- `supertonic-mcp` stdio server (`list_languages`, `list_voices`, `speak`, `preview_voice`).
- Web UI for speaking, the voice library and connection snippets.
- Latency benchmark script and results (`docs/benchmarks.md`).
- README, API reference, integration notes, third-party notices and launch scripts for
  macOS/Linux and Windows.
- Voice building from 1 to 3 reference recordings on an NVIDIA GPU, in a separate worker
  process (the server never imports PyTorch; install with `uv sync --extra builder`). Two
  methods: `accurate` (default; speaker-similarity optimisation after
  supertonic3-voice-clone, about 100 min on a laptop GPU) and `fast` (supertonic.embed's
  WavLM inversion, about 10 to 15 min). Built voices are custom voices with a `build` report,
  the `source_note` and consent.
- `POST /v1/voices/build`, `GET /v1/jobs`, `GET /v1/jobs/{id}`, `DELETE /v1/jobs/{id}`
  (cancel) and `POST /v1/jobs/{id}/finish` (Finish now); one build at a time, 8 waiting,
  persistent jobs, a 150-minute timeout (`SUPERTONIC_BUILDER_TIMEOUT_MIN`).
- Forwarding: `SUPERTONIC_BUILDER_URL` / `SUPERTONIC_BUILDER_API_KEY` send builds from a
  machine without a GPU to a builder and import the finished voice locally.
- MCP tools `build_voice`, `get_job`, `list_jobs` and `finish_job`.
- New voice screen in the web UI: upload or record, method choice, progress, Cancel,
  Finish now and Try it.
- `scripts/setup-builder.ps1` (Windows) and `scripts/setup-builder.sh` (Linux) set up a
  builder: install, CUDA self-test, model downloads
  (`python -m supertonic_server.builder.extract.prefetch`) and the `.env` lines to use.
- Builder guide (`docs/builder.md`) and builder measurements (`docs/benchmarks-builder.md`).

### Changed

- Authentication, a request-body cap (1 MB; voice import 2 MB + 64 KB; `413
  payload_too_large`) and a tunnel check now run in one ASGI guard before routing, so the
  key is verified before any body is read. The OpenAPI pages need the key when one is set.
- Without an API key, requests carrying `CF-Connecting-IP`, `X-Forwarded-For`, `Forwarded`
  or `X-Real-IP` are refused with `403 forwarded_without_key`.
- Whole-file renders (mp3, opus, aac, flac speech and `/v1/tts/timestamps`) are limited to
  20 000 characters; stream longer text as `pcm`/`wav`.
- `pcm` speech runs at realtime priority and uses `SUPERTONIC_REALTIME_STEPS` unless
  `total_steps` is given; realtime work has its own queue allowance.
- Settings are range-checked, `~` is expanded in paths and a blank API key means none.
- Voice names are limited to 100 characters, ids to 64; Windows device names get a suffix.
- `/v1/tts/timestamps` rejects an unknown `response_format` as `400 invalid_request`.

### Fixed

- Realtime sockets no longer fail with `too_many_contexts` after 32 one-turn contexts; only
  live contexts count.
- Ragged or deeply nested style data is rejected on import instead of breaking the voice.
- Sentence splitting is linear on long runs of punctuation (no event-loop stalls).
- Encoding, resampling, timestamp estimation and preview writes run off the event loop.
- MCP `speak` saves WAV files with correct sizes.
- Leftover voice folders no longer block imports, previews never recreate a deleted voice,
  and voice ids come from folder names.
- Truncated speech streams are logged as warnings and closed promptly on disconnect.
- `api_key=` values are redacted from the access log.
- The builder worker's `--self-test` no longer crashes with `OSError: [Errno 22]` when run
  by hand from a Windows console with its output piped.

[Unreleased]: https://github.com/saifulbabo67646/supertonic/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/saifulbabo67646/supertonic/releases/tag/v0.1.0
