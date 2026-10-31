# API reference

Base URL: `http://127.0.0.1:8787` (the examples below use that). When `SUPERTONIC_API_KEY`
is set, every `/v1/*` endpoint except `GET /v1/health`, and the OpenAPI pages `/docs`,
`/redoc` and `/openapi.json`, need `Authorization: Bearer <key>`; add
`-H "Authorization: Bearer $KEY"` to the curl calls. The web UI (`/`) is public. A browser
cannot send that header to `/docs`, so with a key set fetch `/openapi.json` with curl or
browse the docs on a keyless local server.

The key is checked before the body is read, so a bad or missing key is always
`401 invalid_api_key`, even for a malformed body.

## Limits and guard errors

| limit | value | error |
|---|---|---|
| request body | 1 MB; `POST /v1/voices/import` 2 MB + 64 KB; `POST /v1/voices/build` 25 MB + 256 KB | `413 payload_too_large` (counted while the body streams in) |
| streamed speech (`pcm`, `wav`) | 100 000 characters | `400 input_too_long` |
| whole-file speech (`mp3`, `opus`, `aac`, `flac`) and `/v1/tts/timestamps` | 20 000 characters | `400 input_too_long` (stream longer text as `pcm`/`wav`) |
| voice name | 100 characters (ids at most 64) | `400 invalid_request`, `param: "name"` |
| proxy header without a key | requests with `CF-Connecting-IP`, `X-Forwarded-For`, `Forwarded` or `X-Real-IP` while `SUPERTONIC_API_KEY` is unset | `403 forwarded_without_key` |
| foreign host without a key | a `Host` other than `localhost`, `127.0.0.1`, `[::1]`, the bind host or `SUPERTONIC_ALLOWED_HOSTS` (DNS rebinding) | `403 forbidden_host` |
| other web site without a key | an `Origin` other than the server's own or `SUPERTONIC_ALLOWED_ORIGINS` (cross-site requests); requests without `Origin` are not affected | `403 forbidden_origin` |
| queue | `SUPERTONIC_MAX_QUEUE` waiting jobs (realtime work has its own allowance of the same size) | `503 server_busy` |

Errors always look like OpenAI's:

```json
{"error":{"message":"Voice 'nope' not found. Available: F1, F2, F3, F4, F5, M1, M2, M3","type":"invalid_request_error","code":"voice_not_found","param":"voice"}}
```

Unknown voices, languages and out-of-range values are errors; the server never silently
substitutes another voice.

## Health

```bash
curl -s http://127.0.0.1:8787/v1/health
# {"status":"ok","model":"supertonic-3","voices":10,"builder":"none","builder_detail":null,"auth":false,"version":"0.1.0"}
```

`builder` is `"local"` when this machine can build voices, `"remote"` when builds are
forwarded to another server (`SUPERTONIC_BUILDER_URL`) and `"none"` otherwise. For a local
builder `builder_detail` is `{"device":"NVIDIA GeForce RTX 4050","vram_mb":6144,"methods":["accurate","fast"]}`;
for a remote one `{"host":"win-laptop:8787","methods":["accurate","fast"]}`, where `methods`
are the ones the remote reported at its last health check (all methods until it has been
reached once); otherwise `null`. A remote builder is not contacted by this health check, so
`"remote"` does not mean it is up. When the server has an API key, `host` and `device`
are only included for requests that send the key (the health check itself needs none).

## Models

```bash
curl -s http://127.0.0.1:8787/v1/models
# {"object":"list","data":[{"id":"supertonic-3","object":"model","owned_by":"supertone"}]}
```

## Languages

`GET /v1/languages` returns `{"data":[{code,name,sample,spaced}]}` for the 31 languages plus
`na` (unknown language). `spaced: false` (Japanese) means word timing is per character.

```bash
curl -s http://127.0.0.1:8787/v1/languages
```

## Speech (OpenAI compatible)

`POST /v1/audio/speech`

| field | default | notes |
|---|---|---|
| `input` | required | text, up to 100 000 characters for `pcm`/`wav`, 20 000 for other formats |
| `voice` | required | voice id or name, see `/v1/voices` |
| `model` | `supertonic-3` | accepted for compatibility, ignored |
| `response_format` | `mp3` | `mp3`, `opus`, `aac`, `flac`, `wav`, `pcm` |
| `speed` | `1.05` | 0.7 to 2.0 |
| `language` | `en` | language code |
| `total_steps` | `8` (`pcm`: `SUPERTONIC_REALTIME_STEPS`, 3) | denoising steps 1 to 100; fewer is faster and lower quality |
| `sample_rate` | 44100 (`pcm`: 24000) | one of 16000, 22050, 24000, 44100 |
| `instructions` | | accepted for compatibility, ignored |

`pcm` is raw 16-bit little-endian mono; `wav` and `pcm` stream sentence by sentence
(chunked transfer, WAV header with unknown length). Other formats return the whole file.
Responses carry `X-Sample-Rate` and `X-Voice-Id` headers.

`pcm` is treated as the live-agent path: it runs at realtime priority (ahead of other REST
work) and, unless the request sets `total_steps`, uses `SUPERTONIC_REALTIME_STEPS`. If
synthesis fails after the first bytes of a stream were sent, the response simply ends early
(the server logs a warning).

```bash
curl -s http://127.0.0.1:8787/v1/audio/speech \
  -H 'Content-Type: application/json' \
  -d '{"model":"supertonic-3","input":"Hello from Supertonic.","voice":"F1"}' \
  -o speech.mp3

curl -s http://127.0.0.1:8787/v1/audio/speech \
  -H 'Content-Type: application/json' \
  -d '{"input":"Hello.","voice":"M1","response_format":"pcm"}' -o speech.pcm
ffplay -f s16le -ar 24000 -ac 1 speech.pcm
```

## Speech with word timestamps

`POST /v1/tts/timestamps` takes `text`, `voice`, `language`, `speed`, `total_steps` and
`response_format` (`wav` default, or `mp3`; anything else is `400 invalid_request` with
`param: "response_format"`). `text` is limited to 20 000 characters. It returns base64 audio
plus timings.
**Timings are estimated** from sentence durations and word length, not forced-aligned
(`timing_source` says so). Japanese is timed per character (`timing_unit: "character"`).

```bash
curl -s http://127.0.0.1:8787/v1/tts/timestamps \
  -H 'Content-Type: application/json' \
  -d '{"text":"Hello there, world.","voice":"F1","response_format":"mp3"}'
```

```json
{"audio_base64":"SUQzBAAA...","format":"mp3","sample_rate":44100,"duration_ms":1598,
 "voice":"F1","language":"en","timing_source":"estimated","timing_unit":"word",
 "segments":[{"text":"Hello there, world.","start_ms":0,"end_ms":1598}],
 "words":[{"text":"Hello","start_ms":240,"end_ms":500},
          {"text":"there,","start_ms":500,"end_ms":864},
          {"text":"world.","start_ms":864,"end_ms":1280}]}
```

## Voices

Ten built-in presets (`F1` to `F5`, `M1` to `M5`) plus custom voices you import.

Every built-in voice also has a name: `F1` is Mia, `F2` Nora, `F3` Lena, `F4` Sofia, `F5`
Yuna, `M1` Hugo, `M2` Diego, `M3` Ravi, `M4` Felix and `M5` Omar (see
[voices.md](voices.md) for what each sounds like). A name works anywhere an id does, in any
capitalisation: the `voice` field of `/v1/audio/speech` and `/v1/tts/timestamps`, the
realtime WebSocket, the MCP tools and `GET /v1/voices/{id}` (also `/style` and
`/preview`). A reference is matched in this order: exact id, id in any capitalisation,
built-in name, custom voice name (`400 ambiguous_voice` when several custom voices share
it). Responses always carry the canonical id (`voice`, `X-Voice-Id`). Listings give every
voice the same fields; for presets `name` and `description` are the built-in ones. A custom
voice cannot be imported, built or renamed to a built-in name or id:
`409 voice_name_taken`, `param: "name"`.

Ids of custom voices are derived from their name (`my-voice`, `my-voice-2` on collision),
are at most 64 characters, and never use a Windows device name (`con`, `nul`, `com1`, ...: these get
a `-voice` suffix). Names are at most 100 characters. Each custom voice lives in
`SUPERTONIC_DATA_DIR/voices/<id>/`; the folder name is the id.

```bash
curl -s 'http://127.0.0.1:8787/v1/voices?kind=preset'     # filters: kind=preset|custom, tag=...
curl -s http://127.0.0.1:8787/v1/voices/F1                    # or /v1/voices/mia
curl -s http://127.0.0.1:8787/v1/voices/F1/style -o f1.json   # export the style JSON
curl -s -o preview.wav 'http://127.0.0.1:8787/v1/voices/F1/preview?language=en'
```

Import a style JSON (maximum 2 MB), as a JSON body or as multipart:

```bash
curl -s -X POST http://127.0.0.1:8787/v1/voices/import \
  -H 'Content-Type: application/json' \
  -d "{\"name\":\"My F1 copy\",\"tags\":[\"demo\"],\"style\":$(cat f1.json)}"

curl -s -X POST http://127.0.0.1:8787/v1/voices/import \
  -F file=@f1.json -F name="Upload copy" -F tags=demo,upload
```

Both return `201` and the voice object (`id`, `name`, `kind`, `description`, `tags`,
`gender`, `source_note`, `created_at`, `model`, `preview_url`). Edit and delete custom
voices (presets are read-only and answer `400 voice_read_only`):

```bash
curl -s -X PATCH http://127.0.0.1:8787/v1/voices/my-f1-copy \
  -H 'Content-Type: application/json' -d '{"name":"Narrator","tags":["demo","narration"]}'
curl -s -X DELETE http://127.0.0.1:8787/v1/voices/my-f1-copy      # 204
```

## Building voices

Clone a voice from 1 to 3 reference recordings. Building needs a builder: a CUDA machine
with the `builder` extra installed (`GET /v1/health` shows `"builder":"local"`). Without one
every endpoint below answers `503 builder_unavailable` with a hint to set
`SUPERTONIC_BUILDER_URL` or install the builder extra on a CUDA machine. Built voices are
ordinary custom voices with an extra `build` object (`method`, `loss`, `similarity`,
`steps`, `preset_start`, `duration_status`, `seconds`, `stopped_early`, `builder`). They
derive from the Supertonic model, so the OpenRAIL-M terms apply to them too.

`POST /v1/voices/build` takes `multipart/form-data`:

| field | |
|---|---|
| `files` | 1 to 3 audio files (any common format), at most 25 MB in total; 3 to 60 s of speech after trimming |
| `name` | required, at most 100 characters, not a built-in voice's name or id (`409 voice_name_taken`) |
| `description`, `tags` | optional; `tags` is comma-separated (so a tag cannot contain a comma) |
| `source_note` | required: where the recording comes from |
| `consent` | required, the string `true`: you have the right to clone this voice |
| `method` | `accurate` (default, slow) or `fast` |

```bash
curl -s -X POST http://127.0.0.1:8787/v1/voices/build \
  -F files=@take1.wav -F files=@take2.mp3 -F name="Narrator" \
  -F source_note="my own recording" -F consent=true -F method=fast
# 202 {"id":"3f2c...","state":"queued","request":{...},"progress":null,"voice_id":null,"error":null,"builder":"local",...}
```

The job `state` is `queued`, `running`, `succeeded`, `failed` or `cancelled`; on success
`voice_id` names the new voice, on failure `error` has a `code` and `message`. One build
runs at a time; up to 8 more wait in the queue.

```bash
curl -s 'http://127.0.0.1:8787/v1/jobs?limit=20'              # {"data":[job, ...]}, newest first
curl -s http://127.0.0.1:8787/v1/jobs/3f2c...                 # one job, with progress
curl -s -X DELETE http://127.0.0.1:8787/v1/jobs/3f2c...       # cancel (a finished job is returned as is)
curl -s -X POST http://127.0.0.1:8787/v1/jobs/3f2c.../finish  # end the timbre stage early, keep the best so far
```

`finish` ends a running job's timbre optimisation at the next step, keeping the best result
so far; the rhythm matching still runs, then the voice is imported and the job succeeds
with `build.stopped_early: true`. Finishing while models are still loading makes the job
fail with `nothing_to_save`. `finish` is accepted once per job (a second call changes
nothing); on a job that already ended it returns the job unchanged (200). A queued job
gives `409 job_not_running`.

With `SUPERTONIC_BUILDER_URL` (and `SUPERTONIC_BUILDER_API_KEY` when the builder has an API
key) a machine without a GPU forwards each build to that server. The request itself
(`name`, `consent`, `source_note`, ...) is validated locally first; then the builder's health is
checked: if it cannot be reached or has no local builder the request fails at once
with `503 builder_unavailable` (nothing is queued for later). The builder checks the
audio and the method, so its errors (`invalid_reference_audio`, `method_unavailable`, ...)
come back unchanged. The forwarding server keeps its own job
(`builder` is `remote:<host:port>`, `remote_id` is the builder's job id), polls the builder
every 3 s, and on success imports the voice into its own library (`voice_id`; the builder's
copy is `remote_voice_id`) with `build.builder` set to `remote:<host:port>` and `build.remote_job_id` naming the
builder's job (an import is never repeated for the same job). If the builder
cannot be reached for 2 minutes the job fails with `builder_lost` and nothing is imported.
`cancel` and `finish` are passed on to the builder. A cancel while the builder cannot be
reached still cancels the local job, with `error.code` `builder_unreachable` ("Could not
reach the builder; the build may still be running there."). After a restart the forwarding server
resumes following jobs that were still queued or running.

| status | code | meaning |
|---|---|---|
| 400 | `invalid_request` | bad `name`, `method` or file count (`param` says which) |
| 400 | `consent_required` | `source_note` blank or `consent` not `true` |
| 400 | `invalid_reference_audio` | audio unreadable, too short/long or mostly silent (the message says why) |
| 400 | `method_unavailable` | this builder cannot run the method |
| 404 | `job_not_found` | unknown job id |
| 409 | `job_not_running` | `finish` on a job that has not started |
| 413 | `payload_too_large` | upload over the limit |
| 500 | `internal_error` | `finish` could not write the job's stop file (the job keeps running; try again) |
| 502 | `builder_error` | the remote builder answered with something that is not an API error (for example a proxy page) |
| 503 | `builder_unavailable` | no builder, it is shutting down, or the remote builder is unreachable |
| 503 | `builder_busy` | the queue is full |

A job that ends `failed` has `error: {"code", "message"}`; the message never names local
file paths (home and temp folders show as `<home>` and `<tmp>`). A forwarded job reports
the builder's code unchanged.

| `error.code` | meaning |
|---|---|
| `timeout` | the build ran longer than `SUPERTONIC_BUILDER_TIMEOUT_MIN` |
| `interrupted` | the server restarted while the job was queued or running |
| `worker_failed` | the worker process crashed or could not start (the message is its last error line) |
| `out_of_memory` | not enough GPU memory |
| `cuda_unavailable` | the worker found no CUDA device |
| `missing_dependencies` | the builder extra (PyTorch and friends) is not installed or does not import |
| `nothing_to_save` | Finish now arrived while models were still loading, before any style existed |
| `extract_failed` | the extraction raised another error (the message says which) |
| `bad_arguments` | the worker was started with wrong arguments (a bug or a version mismatch) |
| `import_failed` | the voice was built but could not be saved into the library |
| `builder_lost` | forwarded job: the builder could not be reached for 2 minutes, or forgot the job |
| `builder_unreachable` | on a `cancelled` forwarded job: the builder could not be told, so the build may still be running there |
| `internal_error` | an unexpected error in the server itself |

## Realtime WebSocket

`ws://127.0.0.1:8787/v1/audio/speech/websocket`, see the event table in the
[README](../README.md#realtime-websocket).

Query parameters: `voice` (default `SUPERTONIC_DEFAULT_VOICE`), `language` (`en`), `speed`
(1.05), `sample_rate` (24000; 16000, 22050, 24000 or 44100), `max_partial_length` (250
characters; longer unfinished sentences are flushed), `api_key`. `model` is accepted and
ignored. Prefer the `Authorization` header over `?api_key=` (the CLI redacts `api_key=` from
uvicorn's access log, but proxies may still record it). A rejected key, or a proxy header
while the server has no key, arrives as a `conversation.item.tts.failed` event followed by
close code 1008.

Minimal Python client (needs `pip install websockets`):

```python
import asyncio, json, base64, websockets


async def main():
    url = "ws://127.0.0.1:8787/v1/audio/speech/websocket?voice=F1&language=en"
    async with websockets.connect(url) as ws:  # additional_headers={"Authorization": "Bearer ..."}
        await ws.recv()  # session.created
        await ws.send(
            json.dumps(
                {"type": "input_text_buffer.append", "text": "Hello there. How are you today? "}
            )
        )
        await ws.send(json.dumps({"type": "input_text_buffer.commit"}))
        pcm = b""
        while True:
            event = json.loads(await ws.recv())
            if event["type"] == "conversation.item.audio_output.delta":
                pcm += base64.b64decode(event["delta"])  # 24 kHz mono PCM16
            elif event["type"] == "conversation.item.audio_output.done":
                break


asyncio.run(main())
```
