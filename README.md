# Supertonic Server

[![CI](https://github.com/saifulbabo67646/supertonic/actions/workflows/ci.yml/badge.svg)](https://github.com/saifulbabo67646/supertonic/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python 3.11 | 3.12 | 3.13](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13-blue.svg)](pyproject.toml)

**Natural text-to-speech that runs on your own computer.** A free, self-hosted server for
the [Supertonic 3](https://huggingface.co/Supertone/supertonic-3) voice model, with a
friendly web Studio, an OpenAI-compatible API and tools for AI agents.

<!-- DEMO -->

## What you can do

- **Speak 31 languages** with ten natural built-in voices that have names: Mia, Nora, Lena,
  Sofia, Yuna, Hugo, Diego, Ravi, Felix and Omar ([listen and compare](docs/voices.md)).
- **Make your own voice** from a recording of about a minute and use it in every language
  (building needs an NVIDIA GPU, here or on another computer; the voice then runs anywhere).
- **Drop it into apps** that use OpenAI text-to-speech: same `/v1/audio/speech` API, so the
  OpenAI SDK, LiveKit and similar tools work unchanged. Moving from ElevenLabs or Cartesia?
  [Integrations](docs/integrations.md) shows how their features map.
- **Talk in realtime**: a WebSocket streams text in and audio out sentence by sentence, with
  barge-in; about 210 ms to first audio on an Apple M4 CPU.
- **Get word timestamps** for captions and video editing.
- **Let AI agents speak**: an MCP server for Claude Code, Cursor and other assistants.
- **Keep it private and free**: it runs on your machine (CPU is enough), works offline after
  the first start, and refuses outside connections unless you set an access key.

## Quick start

### Double-click (no programming needed)

1. [Download the ZIP](https://github.com/saifulbabo67646/supertonic/archive/refs/heads/main.zip)
   and unzip it.
2. Double-click the start file for your computer:

| Computer | Double-click | The first time |
|---|---|---|
| Mac | `Start Supertonic.command` | if macOS blocks it: **System Settings > Privacy & Security > Open Anyway**, then double-click again |
| Windows | `Start Supertonic.bat` | **More info**, then **Run anyway** |
| Linux | `start-supertonic.sh` | if it opens as text, run `./start-supertonic.sh` in a terminal |

It installs what it needs on the first start (internet required then), starts Supertonic
and opens the Studio in your browser. Close the window to stop it. The
[beginner's guide](docs/getting-started.md) walks through everything, and
[troubleshooting](docs/troubleshooting.md) helps if something goes wrong.

### Set up with a coding agent

Using Claude Code, Codex, Cursor, Gemini CLI or another coding agent? Paste this prompt and
it clones, installs, starts and checks Supertonic for you, following
[AGENTS.md](AGENTS.md):

```text
Set up Supertonic Server (a free, self-hosted text-to-speech server) on this computer.

1. If the current folder is not already the Supertonic repository, clone
   https://github.com/saifulbabo67646/supertonic.git into a folder named "supertonic" in my
   home folder (unless I named another place) and work inside it. If git is not installed,
   download and unzip https://github.com/saifulbabo67646/supertonic/archive/refs/heads/main.zip
   instead.
2. Read AGENTS.md in the repository and follow it step by step. It is the source of truth:
   if anything here disagrees with it, follow AGENTS.md.
3. Done means: the server runs in the background, `uv run supertonic-server check` prints
   PASS, and the Studio is open in my browser.

Rules:
- You may install uv. Ask me before installing anything else system-wide.
- Keep the server on 127.0.0.1. Never make it reachable from the network or the internet
  without an API key, and only if I ask for it.
- If a Supertonic server is already running, reuse it instead of starting another one.

When you are done, tell me: the Studio URL, where the log file is, the exact command to
stop the server, and anything that went wrong or that I need to do.
```

Variations (build voices on an NVIDIA machine, connect a Mac to one, register the MCP
server, replace ElevenLabs or OpenAI in your app): [docs/agent-setup.md](docs/agent-setup.md).

### Developer

You need [uv](https://docs.astral.sh/uv/) (it brings its own Python).

```bash
git clone https://github.com/saifulbabo67646/supertonic.git
cd supertonic
uv sync
uv run supertonic-server serve       # http://127.0.0.1:8787, downloads the model on first start
```

In a second terminal:

```bash
uv run supertonic-server check       # smoke test: health, a speech file, word timestamps
curl -s http://127.0.0.1:8787/v1/audio/speech \
  -H 'Content-Type: application/json' \
  -d '{"input":"Hello from Supertonic.","voice":"Mia"}' -o hello.mp3
```

Or from Python with the OpenAI SDK:

```python
from openai import OpenAI

client = OpenAI(base_url="http://127.0.0.1:8787/v1", api_key="not-needed")
with client.audio.speech.with_streaming_response.create(
    model="supertonic-3", voice="Mia", input="Hello from the OpenAI SDK."
) as response:
    response.stream_to_file("hello.mp3")
```

`serve --open` also opens the Studio, `--port` picks another port, and settings such as
an API key go in a `.env` file ([configuration](docs/configuration.md)). `scripts/serve.sh`
and `scripts\serve.ps1` run `uv sync` and `serve` in one step.

## Documentation

| Topic | Page |
|---|---|
| First steps without a terminal | [Getting started](docs/getting-started.md) |
| Setup with a coding agent, step by step | [AGENTS.md](AGENTS.md), [agent prompts](docs/agent-setup.md) |
| Every endpoint, limits and errors | [API reference](docs/api.md) |
| Realtime WebSocket events | [API reference: realtime](docs/api.md#realtime-websocket) |
| The ten built-in voices | [Voices](docs/voices.md) |
| Building voices from recordings, and forwarding builds from a Mac | [Voice builder](docs/builder.md) |
| Live agents (LiveKit), narration with word timing, replacing hosted TTS | [Integrations](docs/integrations.md) |
| Claude Code, Cursor and other MCP clients | [MCP server](docs/mcp.md) |
| All settings and environment variables | [Configuration](docs/configuration.md) |
| API keys, other computers, Cloudflare Tunnel | [Remote access and security](docs/remote-access.md) |
| Speed measurements | [Latency](docs/benchmarks.md), [voice builder](docs/benchmarks-builder.md) |
| Problems and fixes | [Troubleshooting](docs/troubleshooting.md) |

The full index is [docs/README.md](docs/README.md).

## Requirements

| | Speaking (everyone) | Building voices (optional) |
|---|---|---|
| System | macOS (Apple Silicon or Intel), Windows 10 or 11, Linux | Windows or Linux |
| Memory | 4 GB RAM (the server uses about 500 MB) | 8 GB RAM |
| Disk | about 1 GB | about 6 GB more |
| Graphics card | not needed | NVIDIA with 4 GB of free memory and a current driver |
| Internet | first start only (about 750 MB of downloads) | first setup (about 3 GB more) |

A Mac or any computer without an NVIDIA card can still build voices by sending the work
to one that has it ([forwarding builds](docs/builder.md#forwarding-builds)).

## Performance

On an Apple M4 laptop CPU, the realtime WebSocket starts speaking in about 210 ms, and in
about 410 ms with four conversations at once. Methods and tuning:
[docs/benchmarks.md](docs/benchmarks.md).

## Contributing

Contributions are welcome: see [CONTRIBUTING.md](CONTRIBUTING.md), the
[code of conduct](CODE_OF_CONDUCT.md) and, for security problems, [SECURITY.md](SECURITY.md).
Changes are listed in the [changelog](CHANGELOG.md).

## Licence

The code in this repository is MIT licensed ([LICENSE](LICENSE)). The Supertonic 3 model
weights are licensed separately under **OpenRAIL-M**, which includes use restrictions. Those
restrictions apply to audio you generate and to voices derived from the model. Read the
licence on the [model page](https://huggingface.co/Supertone/supertonic-3) before use. See
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for other components, including the
GPL-built ffmpeg that is used for mp3, opus, aac and flac.

## Acknowledgements

- [Supertone](https://github.com/supertone-inc) for Supertonic 3 and the `supertonic` package.
- [supertonic.embed](https://github.com/kdrkdrkdr/supertonic.embed) by Gyeongmin Kim, whose
  style inversion is the `fast` build method (MIT, vendored and adapted).
- [supertonic3-voice-clone](https://github.com/saurabhv749/supertonic3-voice-clone) by Saurabh
  Verma, whose speaker-similarity optimisation is the `accurate` build method (MIT, vendored
  and adapted).
- [SpeechBrain](https://speechbrain.github.io/) for the ECAPA-TDNN speaker model (Apache-2.0).
