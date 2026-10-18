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
