# Supertonic Server

[![CI](https://github.com/saifulbabo67646/supertonic/actions/workflows/ci.yml/badge.svg)](https://github.com/saifulbabo67646/supertonic/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python 3.11 | 3.12 | 3.13](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13-blue.svg)](pyproject.toml)

A self-hosted text-to-speech server for [Supertonic 3](https://huggingface.co/Supertone/supertonic-3):
31 languages plus automatic language fallback (`na`), an OpenAI-compatible API, a realtime
WebSocket for live agents, estimated word timestamps, an MCP server for AI assistants and a
small web UI. Runs on CPU (ONNX Runtime) on macOS and Windows (Linux should work but is untested).

## Features

- **OpenAI-compatible** `POST /v1/audio/speech` (mp3, opus, aac, flac, wav, pcm) with sentence-level streaming for `wav` and `pcm`.
- **Realtime WebSocket** for streaming LLM text in and audio out, with barge-in (`context.cancel`) and several independent contexts per connection.
- **Word timestamps** (`POST /v1/tts/timestamps`), clearly labelled as estimated.
- **Voice library**: 10 built-in voices, import/export/rename/delete custom styles.
- **Voice building**: clone a voice from 10 to 30 s of speech on an NVIDIA GPU (Windows or Linux), or forward builds from a Mac to such a machine; the result is an ordinary voice that runs on CPU everywhere.
- **MCP server** (`supertonic-mcp`) so Claude Code and other agents can speak, audition and build voices.
- **Web UI** at `/` for speaking, browsing voices and copying connection snippets.
- **Safe by default**: binds to loopback, refuses to start on a public interface without an API key, and while no key is set refuses proxied or tunnelled requests and requests from other web sites (Origin and Host checks).
- **Low latency**: about 210 ms to first audio, 410 ms with four concurrent sessions (Apple M4).

## Quick start

Requires [uv](https://docs.astral.sh/uv/) (it installs Python 3.11+ for you). The model
downloads from Hugging Face on first start.

Clone this repository and change into its folder, then start the server.

macOS / Linux:

```bash
scripts/serve.sh
```

Windows (PowerShell):

```powershell
.\scripts\serve.ps1
```

Both run `uv sync` and then `uv run supertonic-server serve`; extra arguments (`--port 8799`,
`--host 127.0.0.1`) are passed through. Open <http://127.0.0.1:8787> for the web UI, then:

```bash
curl -s http://127.0.0.1:8787/v1/audio/speech \
  -H 'Content-Type: application/json' \
  -d '{"input":"Hello from Supertonic.","voice":"F1"}' -o hello.mp3
```

## Configuration

Set environment variables (prefix `SUPERTONIC_`) or put them in a `.env` file in the
working directory; copy [`.env.example`](.env.example) to start.

| Variable | Default | Description |
|---|---|---|
| `SUPERTONIC_HOST` | `127.0.0.1` | Interface to bind. Anything but loopback requires an API key. |
| `SUPERTONIC_PORT` | `8787` | TCP port (1 to 65535). |
| `SUPERTONIC_API_KEY` | unset | Bearer token clients must send. Required when the host is not loopback or a public URL is set. A blank value means no key. |
| `SUPERTONIC_PUBLIC_URL` | unset | Public URL when behind a tunnel or proxy (for a quick tunnel with a random hostname, any value works). Setting it also requires an API key. |
| `SUPERTONIC_ALLOWED_HOSTS` | unset | Without an API key: extra `Host` names to accept besides `localhost`, `127.0.0.1`, `[::1]` and the bind host (comma-separated). |
| `SUPERTONIC_ALLOWED_ORIGINS` | unset | Without an API key: extra browser origins (for example `http://localhost:3000`) whose pages may call the server, besides its own (comma-separated). |
| `SUPERTONIC_DATA_DIR` | `~/.supertonic-server` | Custom voices and previews (`~` is expanded). |
| `SUPERTONIC_MODEL_DIR` | unset | Local model weights; unset downloads to the Hugging Face cache. |
| `SUPERTONIC_WORKERS` | `0` | Synthesis workers. `0` means `min(4, max(1, cpu_count // 2))`. |
| `SUPERTONIC_INTRA_OP_THREADS` | unset | ONNX threads per worker (at least 1). Unset means `ceil(cpu_count / workers)`. |
| `SUPERTONIC_MAX_QUEUE` | `64` | Waiting synthesis jobs before the server answers 503 (at least 1). Realtime work has its own allowance of the same size, so REST traffic cannot crowd it out. |
| `SUPERTONIC_REALTIME_STEPS` | `3` | Denoising steps (1 to 100) for realtime WebSocket sentences and for `pcm` speech requests that do not set `total_steps`. Other REST requests use `total_steps` (default 8). |
| `SUPERTONIC_DEFAULT_VOICE` | `F1` | Voice for realtime connections that name none. |
| `SUPERTONIC_BUILDER` | `auto` | Voice building: `auto` builds here when this machine has a CUDA GPU and the builder extra, `local` also logs why it cannot, `off` disables it. `SUPERTONIC_BUILDER_URL` takes precedence. |
| `SUPERTONIC_BUILDER_URL` | unset | Another Supertonic server that builds voices for this one (see [docs/builder.md](docs/builder.md)). |
| `SUPERTONIC_BUILDER_API_KEY` | unset | That server's API key. |
| `SUPERTONIC_BUILDER_TIMEOUT_MIN` | `150` | Minutes one build may run before it fails with `timeout` (at least 1). |

`supertonic-server serve` also accepts `--host` and `--port`. The MCP process reads
`SUPERTONIC_BASE_URL` (default `http://127.0.0.1:8787`), `SUPERTONIC_API_KEY` and
`SUPERTONIC_MCP_OUTPUT_DIR` (default `./supertonic-output`).

## Using it from apps

curl: see above, or the full [API reference](docs/api.md).

OpenAI Python SDK (point `base_url` at the server; the key is only checked if you set one):

```python
from openai import OpenAI

client = OpenAI(base_url="http://127.0.0.1:8787/v1", api_key="not-needed")
with client.audio.speech.with_streaming_response.create(
    model="supertonic-3", voice="F1", input="Hello from the OpenAI SDK.", response_format="mp3"
) as response:
    response.stream_to_file("hello.mp3")
```

LiveKit Agents (the `openai.TTS` plugin; `model` and `voice` are passed through):

```python
from livekit.plugins import openai

tts = openai.TTS(
    base_url="http://127.0.0.1:8787/v1", api_key="not-needed", model="supertonic-3", voice="F1"
)
```

Ask for `response_format="pcm"` if your plugin version lets you choose the format: `pcm`
streams sentence by sentence at realtime priority, while compressed formats (mp3, opus, aac,
flac) are rendered as whole files and limited to 20 000 characters.

More patterns (live agents with barge-in, narration with timestamps) are in
[docs/integrations.md](docs/integrations.md).

## Building voices

A voice is a small file of numbers that steers the frozen Supertonic model. The builder
finds new numbers that make the model sound like a reference recording: it synthesises,
lets a speaker-recognition model score the similarity to the reference, nudges the numbers
and repeats. That needs an NVIDIA GPU; the finished voice runs on CPU like the built-in
ones and speaks all 31 languages.

| Method | Time (RTX 4050 Laptop, 6 GB) | Result |
|---|---|---|
| `accurate` (default) | about 100 min, or less with **Finish now** | close likeness |
| `fast` | about 10 to 15 min | rough likeness |

On the GPU machine (Windows or Linux):

```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup-builder.ps1   # Windows
```

```bash
scripts/setup-builder.sh                                            # Linux
```

The script installs the `builder` extra (`uv sync --extra builder`), checks CUDA, downloads
the models and prints the `.env` lines for the builder and for machines that forward to
it. A Mac sets `SUPERTONIC_BUILDER_URL` (over a trusted LAN or an SSH tunnel) and builds
from its own web UI, REST API or MCP tools; the voice lands in its library. Every build
needs a note on where the audio comes from and the speaker's consent. The full guide, with
troubleshooting, is [docs/builder.md](docs/builder.md); measurements are in
[docs/benchmarks-builder.md](docs/benchmarks-builder.md).

## API reference

All endpoints are under `/v1` and, when an API key is set, need `Authorization: Bearer <key>`
(except `GET /v1/health`); so do the OpenAPI pages `/docs`, `/redoc` and `/openapi.json`. The
key is checked before the request body is read. Request bodies are limited to 1 MB (voice
imports: 2 MB plus 64 KB of multipart framing; larger gives `413 payload_too_large`). Full
per-endpoint reference with curl examples: [docs/api.md](docs/api.md).

| Method and path | Purpose |
|---|---|
| `POST /v1/audio/speech` | OpenAI-compatible speech. Extra fields: `language`, `total_steps`, `sample_rate`. `pcm`/`wav` stream (up to 100 000 characters); other formats up to 20 000. |
| `POST /v1/tts/timestamps` | Audio (base64) with estimated segment and word timings (up to 20 000 characters). |
| `GET /v1/voices`, `GET /v1/voices/{id}` | List (filters `kind`, `tag`) and inspect voices. |
| `POST /v1/voices/import` | Import a style JSON (JSON body or multipart `file`, up to 2 MB). |
| `PATCH /v1/voices/{id}`, `DELETE /v1/voices/{id}` | Edit or delete a custom voice. |
| `GET /v1/voices/{id}/style`, `GET /v1/voices/{id}/preview` | Export a style; sample WAV (`?language=`). |
| `GET /v1/languages`, `GET /v1/models`, `GET /v1/health` | Discovery and liveness. |
| `WS /v1/audio/speech/websocket` | Realtime TTS, below. |

## Realtime WebSocket

Connect to `/v1/audio/speech/websocket?voice=F1&language=en&speed=1.05&sample_rate=24000`.
Audio is base64 PCM16 mono at `sample_rate` (16000, 22050, 24000 or 44100). Every client
event may carry a `context_id` (default `default`); contexts are independent utterances on
one socket. Send `Authorization: Bearer <key>` when your client can set headers; `?api_key=`
exists for browsers but query strings tend to end up in logs, so prefer the header.

Client to server:

| Event | Fields | Effect |
|---|---|---|
| `input_text_buffer.append` | `text`, `context_id` | Adds text. Each finished sentence is synthesised and sent immediately; an unfinished one is flushed at `max_partial_length` (default 250) characters. |
| `input_text_buffer.commit` | `context_id` | Flushes the remaining text and ends the item (`audio_output.done`). Committing a context with no pending item sends nothing. |
| `input_text_buffer.clear` | `context_id` | Drops buffered text that was not yet cut into a sentence. |
| `context.cancel` | `context_id` | Barge-in: stops the context, drops unsent audio, replies `context.cancelled`. |
| `tts_session.updated` | `session: {voice, language, speed}`, optional `context_id` | Changes voice, language or speed of one context, or of all if `context_id` is omitted. |

Server to client:

| Event | Fields |
|---|---|
| `session.created` | `session` (`id`, `voice`, `language`, `sample_rate`, `speed`, ...), sent once after connecting. |
| `session.updated` | `context_id` (null if all), `session`. |
| `conversation.item.input_text.received` | `context_id`, `item_id`, `text`: acknowledges an append. |
| `conversation.item.audio_output.delta` | `context_id`, `item_id`, `delta` (base64 PCM16), one per sentence, in order. |
| `conversation.item.audio_output.done` | `context_id`, `item_id`: after the last delta of an item. |
| `context.cancelled` | `context_id`: no further audio for the cancelled work follows. |
| `conversation.item.tts.failed` | `context_id`, optional `item_id`, `error` object (`message`, `type`, `code`, `param`). |

Limits: at most 32 live contexts per connection (a context with text buffered, queued or
being synthesised; idle contexts are forgotten, oldest first, when room is needed, and their
per-context settings revert to the session's) and 4 synthesising at once (others wait their
turn); at most 100 000 characters waiting for synthesis per connection (more gives
`input_too_long`); if the client stops reading and 4 MB of events are queued, synthesis
pauses until it catches up. Authentication or parameter errors arrive as a
`conversation.item.tts.failed` event followed by close code 1008.

## MCP (Claude Code and other agents)

`supertonic-mcp` is a stdio MCP server that talks to a running Supertonic server and saves
audio files on the machine it runs on. Tools: `list_languages`, `list_voices`, `speak`
(optionally with word timestamps) and `preview_voice`, plus voice building:
`build_voice` (reference audio paths, name, `source_note`, `consent`, `method` `accurate` or
`fast`), `get_job`, `list_jobs` and `finish_job`.

Claude Code:

```bash
claude mcp add supertonic \
  --env SUPERTONIC_BASE_URL=http://127.0.0.1:8787 \
  --env SUPERTONIC_API_KEY=your-key-if-set \
  -- uv --directory /path/to/supertonic run supertonic-mcp
```

Any other MCP client (generic JSON config):

```json
{
  "mcpServers": {
    "supertonic": {
      "command": "uv",
      "args": ["--directory", "/path/to/supertonic", "run", "supertonic-mcp"],
      "env": {
        "SUPERTONIC_BASE_URL": "http://127.0.0.1:8787",
        "SUPERTONIC_API_KEY": "your-key-if-set"
      }
    }
  }
}
```

Omit `SUPERTONIC_API_KEY` when the server has none. Files go to `SUPERTONIC_MCP_OUTPUT_DIR`
(default `./supertonic-output`) unless `speak` is given an `output_path`.

## Exposing the server with a Cloudflare Tunnel

Keep the server on loopback and let the tunnel connect to it; do not bind `0.0.0.0`.

```bash
export SUPERTONIC_API_KEY="$(openssl rand -hex 24)"
export SUPERTONIC_PUBLIC_URL="https://tts.example.com"   # your tunnel hostname
scripts/serve.sh                                         # still listens on 127.0.0.1:8787
cloudflared tunnel --url http://127.0.0.1:8787           # quick tunnel; or a named tunnel
```

Setting `SUPERTONIC_PUBLIC_URL` makes the API key mandatory: the server refuses to start
without it (exit status 2). A quick tunnel gets a random hostname, so set any value (for
example `SUPERTONIC_PUBLIC_URL=quick-tunnel`) just to turn the check on. As a second safety
net, a server without a key refuses every request that carries a proxy header
(`CF-Connecting-IP`, `X-Forwarded-For`, `Forwarded`, `X-Real-IP`) with
`403 forwarded_without_key`. Clients then send `Authorization: Bearer <key>`, and WebSocket
clients should use `wss://`. The web UI is served without a key but only does anything useful
once you enter the key.

### Web pages and a keyless server

A server without a key trusts every program on this machine, and a web page open in your
browser could otherwise reach it too (a cross-site form post needs no permission, and DNS
rebinding can even read the answers). So while no key is set the server also refuses:

- a request whose `Host` is not `localhost`, `127.0.0.1`, `[::1]`, the bind host or a name in
  `SUPERTONIC_ALLOWED_HOSTS`: `403 forbidden_host`;
- a browser request whose `Origin` is not the server's own (same scheme, host and port) or
  listed in `SUPERTONIC_ALLOWED_ORIGINS`: `403 forbidden_origin`.

The built-in web UI is same-origin and keeps working, and programs that send no `Origin`
(curl, SDKs, the MCP server) are unaffected. With an API key these checks are off: the key
protects the server, and tunnels and proxies with public host names keep working.

## Performance

Measured on an Apple M4 (10 cores, CPU only) with default settings. Time to first audio for
the first sentence through the realtime WebSocket:

| sessions | p50 (ms) | p95 (ms) |
|---|---|---|
| 1 | about 211 | at most 222 |
| 4 | about 405 | at most 493 |

Methodology, worker/thread/steps tuning and reproduction commands:
[docs/benchmarks.md](docs/benchmarks.md). Realtime uses 3 denoising steps by default for
this reason; audio quality at few steps has not been evaluated, so listen before relying on it.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) and the [code of conduct](CODE_OF_CONDUCT.md).
Report vulnerabilities as described in [SECURITY.md](SECURITY.md).

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
