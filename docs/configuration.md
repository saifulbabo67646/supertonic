# Configuration

Set environment variables (prefix `SUPERTONIC_`) or put them in a `.env` file in the
working directory; copy [`.env.example`](../.env.example) to start.

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
| `SUPERTONIC_BUILDER_URL` | unset | Another Supertonic server that builds voices for this one (see [builder.md](builder.md)). |
| `SUPERTONIC_BUILDER_API_KEY` | unset | That server's API key. |
| `SUPERTONIC_BUILDER_TIMEOUT_MIN` | `150` | Minutes one build may run before it fails with `timeout` (at least 1). |

`supertonic-server serve` also accepts `--host` and `--port`. The MCP process reads
`SUPERTONIC_BASE_URL` (default `http://127.0.0.1:8787`), `SUPERTONIC_API_KEY` and
`SUPERTONIC_MCP_OUTPUT_DIR` (default `./supertonic-output`).

The double-click launchers also read `SUPERTONIC_SKIP_BUILDER=1` (never install the voice
builder extra, even on a machine with an NVIDIA GPU).
