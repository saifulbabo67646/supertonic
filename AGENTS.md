# AGENTS.md

Instructions for coding agents (Claude Code, Codex, Cursor, Gemini CLI, Copilot and others)
that set up, run or change Supertonic Server. Humans can follow it too. The beginner's
guide for people who do not use a terminal is [docs/getting-started.md](docs/getting-started.md).

Supertonic Server is a self-hosted text-to-speech server for the Supertonic 3 model: an
OpenAI-compatible speech API, a realtime WebSocket, word timestamps, an MCP server and a web
UI (the Studio). It runs on CPU on macOS, Windows and Linux. Python package:
`supertonic_server` in `src/`; commands: `supertonic-server` and `supertonic-mcp`.

## Ground rules

- **Stay on this computer.** The server listens on `127.0.0.1` only. Never set
  `SUPERTONIC_HOST` to another address, open a firewall port or start a tunnel unless the
  user asked for it, and then always with an API key (`SUPERTONIC_API_KEY`). The server
  refuses to start on a non-loopback address without one.
- **Ask before installing system-wide software.** uv is fine to install without asking (it
  goes into the user's home folder and needs no administrator rights). Anything else
  (Homebrew packages, apt packages, drivers, CUDA, Python from python.org) needs the user's
  yes first. Nothing else is needed for the server.
- **Do not stop a server you did not start.** Check for a running one first (step 3) and
  reuse it.
- **Do not commit** `.env`, logs, `supertonic-output/` or anything with an API key in it.
- Commands below are run from the repository root. On Windows they are PowerShell; in
  Windows PowerShell 5.1 `curl` is not curl, so use `curl.exe` or `Invoke-RestMethod`.

## 1. Check the prerequisites

| Need | Check | If missing |
|---|---|---|
| uv | `uv --version` | macOS/Linux: `curl -LsSf https://astral.sh/uv/install.sh \| sh`; Windows: `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 \| iex"`. Then open a new shell, or add `~/.local/bin` (Windows: `%USERPROFILE%\.local\bin`) to `PATH`. |
| Git | `git --version` | Ask the user to install it, or download the ZIP from GitHub instead. |
| Internet (first start only) | | The dependencies (about 350 MB) and the model (about 400 MB, from Hugging Face) download once. |
| Disk and memory | | About 1 GB of disk; the running server uses about 500 MB of RAM. The optional voice builder needs about 6 GB more disk and an NVIDIA GPU. |

Python is not a prerequisite: uv downloads a suitable one (3.11 to 3.13) by itself.

## 2. Get the code

```bash
git clone https://github.com/saifulbabo67646/supertonic.git
cd supertonic
```

## 3. Check whether a server is already running

```bash
curl -s http://127.0.0.1:8787/v1/health
```

Windows: `curl.exe -s http://127.0.0.1:8787/v1/health`.

- JSON with `"model":"supertonic-3"`: a Supertonic server is already running there. Reuse
  it: skip to step 5 and do not start a second one.
- Nothing answers (curl prints nothing, exit status 7): start one in step 4.
- Something else answers: port 8787 belongs to another program. Use another port, for
  example `--port 8790`, in every command below (and `--url http://127.0.0.1:8790` for
  `check`).

## 4. Install and start the server

Install the dependencies (creates `.venv` in the repository; takes a minute or two the first
time). `--inexact` keeps the voice builder extra if this machine already has it (step 7); a
plain `uv sync` would remove it.

```bash
uv sync --inexact
```

Start the server in the background with its output in a log file, so your shell is not
blocked.

macOS and Linux:

```bash
nohup uv run supertonic-server serve > supertonic-server.log 2>&1 &
echo $! > supertonic-server.pid
```

Windows (PowerShell):

```powershell
$p = Start-Process uv -ArgumentList "run", "supertonic-server", "serve" -RedirectStandardOutput supertonic-server.log -RedirectStandardError supertonic-server.err.log -WindowStyle Hidden -PassThru
$p.Id | Set-Content supertonic-server.pid
```

On Windows the server's messages go to `supertonic-server.err.log` and the request log to
`supertonic-server.log`. Add `--port <port>` after `serve` to use another port. The log and
pid files are ignored by Git.

Wait until it answers. The first start downloads the model, which can take several minutes
on a slow connection; later starts take a few seconds. These loops wait up to 10 minutes
and stop early, showing the end of the log, if the server process exits.

```bash
for i in $(seq 1 120); do
  curl -sf http://127.0.0.1:8787/v1/health && break
  if ! kill -0 "$(cat supertonic-server.pid)" 2>/dev/null; then
    echo "The server stopped:"; tail -n 20 supertonic-server.log; break
  fi
  sleep 5
done
```

```powershell
for ($i = 0; $i -lt 120; $i++) {
  try { Invoke-RestMethod http://127.0.0.1:8787/v1/health; break } catch { }
  if (-not (Get-Process -Id (Get-Content supertonic-server.pid) -ErrorAction SilentlyContinue)) {
    "The server stopped:"; Get-Content supertonic-server.err.log -Tail 20; break
  }
  Start-Sleep 5
}
```

If it does not come up, read the end of the log file and look for the message in
[Common failures](#9-common-failures).

**For a person rather than an agent**, the double-click launchers (`Start
Supertonic.command` on macOS, `Start Supertonic.bat` on Windows, `start-supertonic.sh` on
Linux) do all of the above in a window and open the Studio; closing the window stops the
server. In a terminal the same is `uv run supertonic-server launch`: it reuses a running
server, otherwise picks a free port from 8787 to 8799, starts, and opens the browser once
the server is ready (`--no-open` to skip that). Both run in the foreground and keep running
until stopped, so an agent should only use them when the user wants that window.

## 5. Verify

Health check:

```bash
curl -s http://127.0.0.1:8787/v1/health
```

Expected (the numbers can differ: `voices` counts custom voices too, and `builder` is
`"local"` or `"remote"` when voice building is set up):

```json
{"status":"ok","model":"supertonic-3","voices":10,"builder":"none","builder_detail":null,"auth":false,"version":"0.1.0"}
```

Smoke test (makes a speech file and word timestamps; the same command on every system):

```bash
uv run supertonic-server check
```

Expected:

```text
Checking the Supertonic server at http://127.0.0.1:8787
ok  health: version 0.1.0, 10 voices, builder none
ok  speech: 15299 bytes of MP3 written to supertonic-output/smoke-test.mp3
ok  word timestamps: Hello / there, / world. (1598 ms of audio)
PASS
```

The byte count can differ slightly. It ends with `PASS` and exit status 0, or prints `FAIL:`
with the reason and exits with 1. Options: `--url http://127.0.0.1:<port>`, `--api-key <key>`
(default: `SUPERTONIC_API_KEY`), `--out <file>`.

The Studio is at <http://127.0.0.1:8787/>. Open it for the user with `open <url>` (macOS),
`start <url>` (Windows) or `xdg-open <url>` (Linux).

## 6. Stop the server

macOS and Linux:

```bash
kill "$(cat supertonic-server.pid)"
```

Windows (`/T` matters: it also stops the server process that `uv` started; taskkill may
print one "could not be terminated" line for a process that already ended, which is fine):

```powershell
taskkill /PID (Get-Content supertonic-server.pid) /T /F
```

A launcher window stops with Ctrl+C or by closing it.

## 7. Optional: the voice builder (NVIDIA GPU)

Building a voice from a recording needs an NVIDIA GPU (4 GB of free VRAM, `nvidia-smi`
must work) on Windows or Linux. The built voice then runs on CPU everywhere. Ask the user
before this step: it downloads about 3 GB.

Stop the server (step 6), then:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup-builder.ps1   # Windows
```

```bash
scripts/setup-builder.sh                                            # Linux
```

The script installs the `builder` extra, checks CUDA, downloads the models and prints `.env`
lines. Start the server again as in step 4. `GET /v1/health` then shows `"builder":"local"`.
From now on install with `uv sync --extra builder` or `uv sync --inexact`: a plain
`uv sync` removes the builder again.

**A Mac (or any machine without a GPU) can forward builds** to such a machine. On the
forwarding machine put this in `.env` and restart:

```dotenv
SUPERTONIC_BUILDER_URL=http://127.0.0.1:8788
SUPERTONIC_BUILDER_API_KEY=<the builder's SUPERTONIC_API_KEY, if it has one>
```

with an SSH tunnel to the GPU machine kept open (`ssh -N -L 8788:127.0.0.1:8787 <gpu-machine>`),
or the GPU machine's LAN address instead of the tunnel when the user wants the builder on
the network (that needs an API key on the builder and a firewall rule; ask first). Health
on the forwarding machine then shows `"builder":"remote"`. Full guide:
[docs/builder.md](docs/builder.md).

## 8. Connect AI assistants and apps

**Claude Code** (the server must be running; use the absolute path of this repository):

```bash
claude mcp add supertonic --scope user --env SUPERTONIC_BASE_URL=http://127.0.0.1:8787 -- uv --directory /absolute/path/to/supertonic run supertonic-mcp
```

Add `--env SUPERTONIC_API_KEY=<key>` if the server has a key. Check with
`claude mcp get supertonic`: it shows `Status: ✔ Connected`. Tools: `speak`, `list_voices`,
`list_languages`, `preview_voice`, `build_voice`, `get_job`, `list_jobs`, `finish_job`.
Audio files go to `supertonic-output/` in the repository unless `speak` gets an
`output_path`.

**Other MCP clients** (Cursor, Codex, Gemini CLI, Claude Desktop, ...) take the same
command in their JSON config:

```json
{
  "mcpServers": {
    "supertonic": {
      "command": "uv",
      "args": ["--directory", "/absolute/path/to/supertonic", "run", "supertonic-mcp"],
      "env": { "SUPERTONIC_BASE_URL": "http://127.0.0.1:8787" }
    }
  }
}
```

**Apps that use OpenAI text-to-speech**: base URL `http://127.0.0.1:8787/v1`, model
`supertonic-3`, a voice name such as `Mia` (all ten: [docs/voices.md](docs/voices.md)), any
API key when the server has none. Apps written for ElevenLabs or Cartesia need their speech
calls changed: see [docs/integrations.md](docs/integrations.md) and the
[API reference](docs/api.md).

## 9. Common failures

| Symptom | Fix |
|---|---|
| `uv: command not found` right after installing uv | Open a new shell, or `export PATH="$HOME/.local/bin:$PATH"` (Windows: `$env:Path = "$env:USERPROFILE\.local\bin;$env:Path"`). |
| `curl -s ...` hangs, asks for input or fails with a parameter error in Windows PowerShell | `curl` is an alias for `Invoke-WebRequest` there. Use `curl.exe` or `Invoke-RestMethod`. |
| `address already in use` (`[Errno 48]` macOS, `[Errno 98]` Linux, `[WinError 10048]` Windows) | Another program has the port. Step 3 tells you whether it is Supertonic; otherwise add `--port 8790`. |
| `error: ...` and exit status 2 at start | Unsafe settings, for example `SUPERTONIC_HOST` other than loopback or `SUPERTONIC_PUBLIC_URL` without `SUPERTONIC_API_KEY`. Remove them from the environment and `.env`, or set a key. |
| `403` with `forwarded_without_key` | The request went through a proxy (`HTTP_PROXY` is set). Bypass it for localhost: `curl --noproxy '*' ...` or `NO_PROXY=127.0.0.1,localhost`. |
| `403` with `forbidden_host` | Use `127.0.0.1` or `localhost` in the URL, not the machine's name or LAN address. |
| `401 invalid_api_key` | The server has an API key: send `Authorization: Bearer <key>` (`check --api-key <key>`). |
| The model download fails or stalls | Check the connection to `huggingface.co` (a company proxy or firewall may block it) and start again; a half-finished download is never used. |
| `UnicodeEncodeError` or `charmap` errors on Windows | Set `$env:PYTHONUTF8 = '1'` and start again. |
| `"builder":"none"` on a machine with an NVIDIA GPU | The builder extra is not installed, or a plain `uv sync` removed it. Run the setup script (step 7), or `uv sync --extra builder`, and restart. |
| The server stops when the agent's command ends | Your tool kills background processes. Ask the user to start a launcher (step 4) instead. |

More, for the launchers and for people: [docs/troubleshooting.md](docs/troubleshooting.md).

## 10. Definition of done

- [ ] `uv run supertonic-server check` prints `PASS` (with `--url` if not on port 8787).
- [ ] The server listens on `127.0.0.1` only (or the user explicitly asked otherwise and an
      API key is set).
- [ ] You have told the user: the Studio URL, how the server was started, where the log
      is, and the exact command to stop it (step 6).
- [ ] If asked for: the voice builder shows `"builder":"local"` (or `"remote"` on the
      forwarding machine), and `claude mcp get supertonic` shows `Connected`.
- [ ] Nothing system-wide was installed without the user's yes, and no files were changed
      in the repository except `.env` (if the user wanted settings), logs and the pid file.

## Working on the code

For agents changing Supertonic itself. Details: [CONTRIBUTING.md](CONTRIBUTING.md).

```bash
uv sync                          # runtime and dev dependencies
uv run pytest                    # unit and API tests (real-model and GPU tests are skipped)
uv run ruff check .
uv run ruff format --check .
uv run mypy                      # strict
```

All four must pass before a commit; CI runs them on Linux, macOS and Windows with Python
3.11 to 3.13. `uv run pytest -m model` needs the real weights, `-m gpu` a CUDA GPU and the
builder extra.

| Path | What lives there |
|---|---|
| `src/supertonic_server/cli.py` | `supertonic-server serve`, `launch` and `check` |
| `src/supertonic_server/launch.py`, `smoke.py` | Desktop start (port choice, browser) and the smoke test |
| `src/supertonic_server/api/` | FastAPI app, request guards, routes (`routes/`), realtime WebSocket (`realtime/`) |
| `src/supertonic_server/engine/` | Model interface, priority scheduler, sentence streaming |
| `src/supertonic_server/voices/` | Voice library, built-in names, style validation and storage |
| `src/supertonic_server/audio/`, `text/` | Encoding and resampling; languages and sentence splitting |
| `src/supertonic_server/builder/` | Voice building: job runner, GPU worker, the `accurate` and `fast` methods |
| `src/supertonic_server/mcp/` | The `supertonic-mcp` stdio server |
| `src/supertonic_server/core/` | Settings (`config.py`), errors, limits, log redaction |
| `src/supertonic_server/web/` | The Studio: plain ES modules and CSS, no build step |
| `tests/` | `unit/`, `api/`, `mcp/`, `web/`, plus `integration/` (real model) and `gpu/`; fakes in `tests/fakes*.py` |
| `scripts/` | Launch, serve, builder setup and benchmark scripts |
| `docs/` | User and reference documentation ([index](docs/README.md)) |

Conventions:

- Full type hints (`mypy --strict`), ruff with line length 100, Google-style docstrings.
- Modules stay under about 300 lines; split along a real seam.
- Domain packages (`engine`, `voices`, `audio`, `text`, `builder`) never import `api` or `mcp`.
- New routes: schema in `api/schemas.py`, handler in `api/routes/`, registered in `ROUTERS`,
  errors as `ApiError`, tests in `tests/api/`, documented in `docs/api.md`.
- Behaviour changes need tests and a line under `Unreleased` in `CHANGELOG.md`.
- Conventional Commits (`feat:`, `fix:`, `docs:`, ...).
- Text a user reads (Studio, launcher messages, `docs/getting-started.md`,
  `docs/troubleshooting.md`) uses plain, friendly words.
- Never put personal names, home-folder paths, host names or IP addresses of a real machine
  in tracked files; use `127.0.0.1`, `<gpu-machine>` or `example.com`.
