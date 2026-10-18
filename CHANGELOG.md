# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to
[Semantic Versioning](https://semver.org/).

## [Unreleased]

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
