# API reference

Base URL: `http://127.0.0.1:8787` (the examples below use that). When `SUPERTONIC_API_KEY`
is set, every endpoint except `GET /v1/health` and the web UI needs
`Authorization: Bearer <key>`; add `-H "Authorization: Bearer $KEY"` to the curl calls.

Errors always look like OpenAI's:

```json
{"error":{"message":"Voice 'nope' not found. Available: F1, F2, F3, F4, F5, M1, M2, M3","type":"invalid_request_error","code":"voice_not_found","param":"voice"}}
```

Unknown voices, languages and out-of-range values are errors; the server never silently
substitutes another voice.

## Health

```bash
curl -s http://127.0.0.1:8787/v1/health
# {"status":"ok","model":"supertonic-3","voices":10,"builder":"none","auth":false,"version":"0.1.0"}
```

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
| `input` | required | text, up to 100 000 characters |
| `voice` | required | voice id or name, see `/v1/voices` |
| `model` | `supertonic-3` | accepted for compatibility, ignored |
| `response_format` | `mp3` | `mp3`, `opus`, `aac`, `flac`, `wav`, `pcm` |
| `speed` | `1.05` | 0.7 to 2.0 |
| `language` | `en` | language code |
| `total_steps` | `8` | denoising steps 1 to 100; fewer is faster and lower quality |
| `sample_rate` | 44100 (`pcm`: 24000) | one of 16000, 22050, 24000, 44100 |
| `instructions` | | accepted for compatibility, ignored |

`pcm` is raw 16-bit little-endian mono; `wav` and `pcm` stream sentence by sentence
(chunked transfer, WAV header with unknown length). Other formats return the whole file.
Responses carry `X-Sample-Rate` and `X-Voice-Id` headers.

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
`response_format` (`wav` default, or `mp3`). It returns base64 audio plus timings.
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

Ten built-in presets (`F1` to `F5`, `M1` to `M5`) plus custom voices you import. Ids of
custom voices are derived from their name (`my-voice`, `my-voice-2` on collision).

```bash
curl -s 'http://127.0.0.1:8787/v1/voices?kind=preset'     # filters: kind=preset|custom, tag=...
curl -s http://127.0.0.1:8787/v1/voices/F1
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

## Realtime WebSocket

`ws://127.0.0.1:8787/v1/audio/speech/websocket`, see the event table in the
[README](../README.md#realtime-websocket).

Query parameters: `voice` (default `SUPERTONIC_DEFAULT_VOICE`), `language` (`en`), `speed`
(1.05), `sample_rate` (24000; 16000, 22050, 24000 or 44100), `max_partial_length` (250
characters; longer unfinished sentences are flushed), `api_key`. `model` is accepted and
ignored. Prefer the `Authorization` header over `?api_key=`.

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
