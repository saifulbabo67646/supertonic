# Voice builder

Build a new Supertonic 3 voice from a few seconds of someone's speech. Building needs an
NVIDIA GPU with CUDA; the voice it produces is an ordinary voice file that any Supertonic
server, GPU or not, can use.

## How it works, in plain words

Supertonic 3 is never retrained or changed. Every voice, including the ten built-in ones,
is just a small file of numbers that steers the frozen model: about 13 000 numbers in two
arrays, `style_ttl` (50 × 256, the timbre: what the voice sounds like) and `style_dp`
(8 × 16, the rhythm: how fast and with what pauses it speaks). Building a voice means
finding numbers that make the model sound like your reference recording.

There is no formula for that, so the builder searches:

1. It starts from the built-in voice that already sounds most like the reference, among
   the ones with about the same pitch (see [the start voice](#the-start-voice)).
2. It has the model speak a sentence with the current numbers.
3. A separate "judge" model listens to that audio and to the reference and scores how
   similar the two speakers sound.
4. Because the whole chain is differentiable, the builder can tell which way to nudge each
   of the 13 000 numbers to raise the score. It nudges them a little and goes back to step 2.

After a few hundred to a few thousand rounds the score stops improving and the builder
keeps the best numbers it saw. Finally it measures how fast the reference speaker talks and
adjusts the rhythm array so the new voice speaks at a similar rate.

The judge compares *speakers*, not words, and the training sentences rotate, so what is
learned is the voice rather than any particular sentence. The style arrays are shared by
all 31 languages, so a voice built from English speech also speaks Japanese, Korean and the
rest, usually with the same character (in the first measurements the judge scores were as high
for Japanese as for English; see [benchmarks-builder.md](benchmarks-builder.md)).

The two build methods differ in the judge they use:

| | `accurate` (default) | `fast` |
|---|---|---|
| Judge | ECAPA-TDNN speaker verification model (SpeechBrain), cosine similarity | WavLM-Large layer statistics (supertonic.embed) |
| Steps | up to 3000 (stops early if the loss reaches 0.015) | up to 1000, usually stops after a few hundred |
| Time on a laptop GPU (RTX 4050 Laptop, 6 GB) | about 100 min | about 10 to 15 min |
| Likeness | close; recognisably the speaker | a rough likeness: right gender, pitch range and colour |
| Use it for | the voice you will keep | trying a recording out, or when time matters more than likeness |

`accurate` optimises the same ECAPA score its report shows as `similarity`, so that number
is optimistic: listen to the result before relying on it.

The result is imported into the voice library like any custom voice (`kind: "custom"`)
with an extra `build` report. Synthesis with it runs on the CPU at normal speed; the GPU
is needed only while building.

Built voices derive from the Supertonic 3 model, so its **OpenRAIL-M** licence applies to
them and to everything they say. Only build voices of people who agreed to it; every build
requires a `source_note` (whose voice, where the audio comes from) and `consent=true`, and
both are stored with the voice.

### The start voice

Neither judge hears pitch well, and the search does not move far from where it starts: a
build that starts from a female voice ends with a female-sounding voice, whatever the
score says. So the start voice is chosen by pitch first:

1. The builder measures the median pitch (fundamental frequency, F0) of the reference: the
   middle value over its voiced 40 ms frames, searched between 60 and 400 Hz with the YIN
   method (`builder/extract/common/pitch.py`).
2. In the `preset` stage it has each of the ten built-in voices speak the first sentence,
   scores it with the method's judge and measures its pitch from the same audio. The
   progress line shows both, for example `F4: 0.3123 · 198 Hz`.
3. Only the built-in voices within about ±22% of the reference's pitch (a log-distance of
   0.2) compete; when none is that close, the two nearest by pitch do. Among them the best
   judge score wins. When the reference's pitch cannot be measured (too little voiced
   speech), the best score over all ten wins, as before.

The worker log names the chosen voice and the reason, for example `start preset M1 (loss 0.4012,
136 Hz): lowest loss of 3 presets near 129 Hz`.

### The pitch check

After the build the new voice speaks one sentence and its median pitch is measured the
same way. The report keeps both pitches and whether they match (within the same ±22%):
`pitch_reference_hz`, `pitch_voice_hz` and `pitch_match`. When they do not match, the
Studio's finished build says "This voice sounds higher (or lower) than your recording. Try
making it again with a longer, clearer recording." A short, noisy or whispered recording
is the usual cause: there is too little clear voice to measure or to copy.

## Requirements

- An NVIDIA GPU with at least 4 GB of free VRAM (a full `accurate` build peaked at about
  2.7 GB on top of the desktop's own use; `fast` at about 3.8 GB) and a recent driver
  (`nvidia-smi` must work). CUDA itself comes with PyTorch; no separate toolkit is needed.
- Windows 10/11 or Linux, with [uv](https://docs.astral.sh/uv/).
- About 6 GB of disk for PyTorch with CUDA and the models.
- macOS cannot build (no CUDA). A Mac runs the server as usual and forwards builds to a
  GPU machine, see [Forwarding builds](#forwarding-builds).

## Setting up a builder

The setup script installs the `builder` extra (PyTorch with CUDA and the other build
dependencies), checks that the build worker sees the GPU and both methods and downloads
every model a build needs. Building on this machine needs no `.env` changes. At the end it
also prints `.env` lines for [a builder on a trusted LAN](#over-a-trusted-lan); use them
only if you want that.

Windows (PowerShell 5.1 or 7):

```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup-builder.ps1
```

Linux:

```bash
scripts/setup-builder.sh
```

What it does, step by step (useful if you prefer to do it by hand):

```bash
uv sync --extra builder
uv run python -m supertonic_server.builder.worker --self-test
# {"type": "probe", "torch": "2.9.1+cu126", "cuda": true, "device": "NVIDIA GeForce RTX 4050 Laptop GPU", "vram_mb": 6140, "methods": ["accurate", "fast"]}
uv run python -m supertonic_server.builder.extract.prefetch
# ok supertonic-3 ...   ok wavlm-large microsoft/wavlm-large   ok ecapa .../supertonic-ecapa
```

The models go to the usual caches: Supertonic 3 where the server keeps it (the
`supertonic` package's cache, or `SUPERTONIC_MODEL_DIR`), WavLM-Large into the Hugging
Face hub cache, and the ECAPA model into `<Hugging Face hub cache>/supertonic-ecapa`
(`HF_HUB_CACHE` / `HF_HOME` move both). `prefetch --model-dir <dir>` puts Supertonic 3 in
`<dir>` instead (use the same directory as `SUPERTONIC_MODEL_DIR`); the other two stay put.

Then start the server (`scripts\serve.ps1` or `scripts/serve.sh`). With the builder extra
installed and a GPU present it builds locally: `GET /v1/health` shows `"builder":"local"`
with the device, VRAM and methods. You can build from the web UI (**New voice**), the REST
API ([api.md](api.md#building-voices)) or the MCP tools (`build_voice`, `get_job`,
`list_jobs`, `finish_job`).

`SUPERTONIC_BUILDER` controls this: `auto` (default) builds locally when it can and stays
quiet when it cannot, `local` logs an error when the GPU or the extra is missing, `off`
disables building.

## Forwarding builds

A machine without a GPU (a Mac, a small server) can hand builds to a builder and receive
the finished voice in its own library. Set on the forwarding machine:

```dotenv
SUPERTONIC_BUILDER_URL=http://<builder-address>:8787
SUPERTONIC_BUILDER_API_KEY=<the builder's SUPERTONIC_API_KEY>
```

Its `GET /v1/health` then shows `"builder":"remote"`. Each build is checked locally, sent to
the builder, followed there (every 3 s) and imported on success with `build.builder` set to
`remote:<host:port>`; the builder keeps its own copy too. Cancel and Finish now are passed
on. If the builder is unreachable when you start a build, the request fails at once with
`503 builder_unavailable` (nothing is queued for later); if it disappears during a build,
the job fails with `builder_lost` after 2 minutes and nothing is imported.

There are two ways to reach the builder.

### Over a trusted LAN

On the builder, bind to all interfaces and set a key (the setup script prints these lines
with a random key and the machine's LAN address):

```dotenv
SUPERTONIC_HOST=0.0.0.0
SUPERTONIC_API_KEY=<random key>
```

The server refuses to start on a non-loopback address without a key. On Windows, inbound
connections also need a firewall rule; the setup script prints it and adds it when run as
Administrator with `-OpenFirewall`:

```powershell
New-NetFirewallRule -DisplayName "Supertonic" -Direction Inbound -Protocol TCP -LocalPort 8787 -Action Allow -Profile Private
```

On Linux, allow the port from your LAN only (for example
`sudo ufw allow from 192.168.0.0/16 to any port 8787 proto tcp`). Traffic is plain HTTP, so
use this only on a network you trust.

### Over an SSH tunnel

If you can `ssh` from the forwarding machine to the builder, nothing has to listen on the
network and no firewall rule is needed. Leave the builder on loopback (the default
`SUPERTONIC_HOST=127.0.0.1`; an API key is optional here, since only the tunnel reaches
it), and on the forwarding machine open a tunnel from a local port to the builder's
loopback port:

```bash
ssh -N -L 8788:127.0.0.1:8787 user@builder-host     # keep it running (or add -f)
```

```dotenv
SUPERTONIC_BUILDER_URL=http://127.0.0.1:8788
SUPERTONIC_BUILDER_API_KEY=<the builder's SUPERTONIC_API_KEY, only if it has one>
```

Windows 10/11 include an OpenSSH server (Settings > System > Optional features). The
traffic is encrypted by SSH. If the tunnel drops during a build, the job fails with
`builder_lost` after 2 minutes; the build itself keeps running on the builder and its voice
lands in the builder's library.

## During a build

The reference audio is decoded and checked while the build request is answered, before the
job exists. The job state is `queued`, then `running` with a stage: `loading`, `preset` (the
start-voice scan, one line per built-in voice with its score and pitch), `timbre` (the optimisation, with step, total and loss), `duration`
(the rhythm) and `saving`. One build runs at a time
per builder; up to 8 more wait, and a ninth gets `503 builder_busy`.

- **Cancel** (`DELETE /v1/jobs/{id}`, the Cancel button) stops the worker and its whole
  process tree within seconds. The job ends `cancelled` and nothing is imported.
- **Finish now** (`POST /v1/jobs/{id}/finish`, the Finish now button, MCP `finish_job`)
  ends the timbre stage: the optimisation stops at the next step and keeps the best numbers
  found so far. The rhythm matching (`duration`, 2 to 5 minutes) still runs in full, then
  the voice is saved and imported; the UI shows "Finishing: matching the speaking pace" in
  the meantime. The job succeeds with `build.stopped_early: true` and a real
  `duration_status` (for example `converged`). An `accurate` build is already close to the
  speaker after a few hundred steps (similarity about 0.8 for the test voice after 300
  steps), so this is a good way to get a usable voice sooner. Finishing during the preset
  scan chooses among the presets measured so far, by the same rules; finishing while models are still loading
  (before any style exists) fails with `nothing_to_save`. Finish now is accepted once per
  job: a second press while it is finishing changes nothing, so the rhythm stage cannot be
  cut short that way. Only when the timbre stage ended on its own does a Finish now during
  the rhythm stage stop it (`duration_status: "stopped"`, the start preset's rhythm is
  kept). Finish on a job that already ended returns it unchanged.
- A build that runs longer than `SUPERTONIC_BUILDER_TIMEOUT_MIN` (default 150) fails with
  `timeout`. A server restart marks unfinished local jobs `failed` (`interrupted`). Jobs
  are kept for 7 days under `<data dir>/jobs/<id>/` with `worker.log` and `progress.jsonl`.

## Build report

Every build stores a report in the voice's `build` metadata: `method`, `preset_start`
(the start voice, see [the start voice](#the-start-voice)), `preset_distance` (that preset's loss in the scan), `loss`
(the best loss reached), `steps` (`accurate`: steps run; `fast`: the step that reached the
best loss), `duration_status`, `rate_ref` and `rate_final` (syllable rate of the reference
and of the result), `seconds`, `stopped_early` and `builder` (`local` or
`remote:<host:port>`), and the [pitch check](#the-pitch-check): `pitch_reference_hz` and
`pitch_voice_hz` (median pitch in Hz of the recording and of the new voice, `null` when it
could not be measured) and `pitch_match` (`true` when they are within about ±22%, `false`
when not, `null` when either is unknown). `accurate` adds `similarity` (= 1 - loss, ECAPA cosine similarity)
and `best_step` (the step that reached the best loss; 0 means the start preset was kept).
For `accurate` the scan measures every preset on the first training sentence while the
descent rotates through all sixteen, so `loss` and `preset_distance` come from different
sentences.

## Good reference audio

- 30 to 60 seconds of one speaker, no music or other voices; 1 to 3 files, any common
  format, at most 25 MB in total. Speech must total 3 to 60 s after silence is trimmed.
- Close microphone, little room echo, natural reading voice. The voice copies what it
  hears, including noise and room colour.
- To try the builder before you have a recording, use a built-in voice as the reference:

  ```bash
  curl -s http://127.0.0.1:8787/v1/audio/speech \
    -H 'Content-Type: application/json' \
    -d '{"input":"<a paragraph of about 40 seconds>","voice":"Hugo","response_format":"wav"}' \
    -o reference.wav
  ```

- Recordings that are mostly silence are rejected (`invalid_reference_audio` with the
  reason), as are files that are not audio.

## Known limitations

- A forwarded build whose request times out after the builder already accepted it (rare:
  only when uploading and checking the audio takes over 2 minutes) leaves that job running
  on the builder, and a retry queues behind it. Cancel it on the builder (`GET /v1/jobs`
  there).

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `GET /v1/health` shows `"builder":"none"` on the GPU machine | The builder extra is missing or PyTorch does not see CUDA. Run `uv run python -m supertonic_server.builder.worker --self-test`; set `SUPERTONIC_BUILDER=local` to get the reason in the server log. |
| Self-test says `"cuda": false` | Driver too old or missing (`nvidia-smi` must work), or a CPU-only PyTorch was installed. Re-run `uv sync --extra builder`; on Windows and Linux it pulls the CUDA 12.6 wheels. |
| First build sits in `loading` for minutes | First-run downloads (Supertonic 3, WavLM-Large about 1.2 GB, ECAPA about 80 MB). Run the setup script or `python -m supertonic_server.builder.extract.prefetch` beforehand. |
| Job fails `out_of_memory` | Not enough free VRAM. Close other GPU programs (games, browsers with hardware acceleration, other ML jobs) and retry; `accurate` needs about 2.7 GB, `fast` about 3.8 GB. |
| `.env` or JSON written from PowerShell is not read correctly | In Windows PowerShell 5.1, `>` and `Out-File` write UTF-16, which the server cannot read, and `-Encoding utf8` adds a byte-order mark (fine for `.env`, which the server reads as UTF-8 with or without one, but not for JSON files). Write `.env` with `Set-Content .env 'NAME=value' -Encoding ascii`; write other files with an editor, from Python, or with `[IO.File]::WriteAllText($path, $text, (New-Object Text.UTF8Encoding $false))`. |
| `UnicodeEncodeError` / `charmap` codec errors in logs on Windows | The console uses cp1252. The server starts the worker with `PYTHONUTF8=1`; set it yourself (`$env:PYTHONUTF8 = '1'`) when running the worker or scripts by hand. |
| `torchaudio` complains about missing FFmpeg DLLs on Windows | torchaudio 2.9 needs FFmpeg *shared* libraries to load audio files. The builder never calls `torchaudio.load` (it decodes with soundfile and the bundled ffmpeg), so this only affects your own scripts. |
| The new voice sounds higher or lower than the speaker (`pitch_match: false`) | The recording has too little clear voice for the builder to measure and copy. Record again: 30 to 60 seconds, close to the microphone, in a normal speaking voice, then build again. Voices built before the start voice was chosen by pitch can start from the wrong built-in voice; build those again too. |
| Forwarding machine: `503 builder_unavailable` | The builder URL is wrong, the builder is not running, the key does not match, the firewall blocks the port or the SSH tunnel is down. `curl -H "Authorization: Bearer <key>" <builder-url>/v1/health` from the forwarding machine must show `"builder":"local"`. |
| Forwarded job failed `builder_lost` | The builder could not be reached for 2 minutes (sleep, network change, tunnel closed). The builder may still finish the build into its own library; export it from there and import it. |

## Debugging knobs

| Variable | Default | Effect |
|---|---|---|
| `SUPERTONIC_BUILDER_ACCURATE_STEPS` | unset (3000) | Caps the `accurate` descent at this many steps, for quick test builds. A positive integer; anything else fails the build. Read by the builder worker from the process environment (set it where the builder server starts; a `.env` entry is not passed on): `SUPERTONIC_BUILDER_ACCURATE_STEPS=60 uv run supertonic-server serve` on macOS and Linux; on Windows `$env:SUPERTONIC_BUILDER_ACCURATE_STEPS = '60'` before `scripts\serve.ps1`, or `cmd /c set SUPERTONIC_BUILDER_ACCURATE_STEPS=60&& uv run supertonic-server serve ...` in the background start of [AGENTS.md](../AGENTS.md) step 4. Loading, the preset scan and the rhythm stage do not shrink with it: a 60-step build still took about 9 minutes on an RTX 4050 Laptop GPU. |

Measured timings and VRAM: [benchmarks-builder.md](benchmarks-builder.md).
