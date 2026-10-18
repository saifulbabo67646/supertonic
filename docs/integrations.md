# Integration notes

Generic recipes for two common ways to use Supertonic Server. Replace the base URL and key
with your own (`SUPERTONIC_BASE_URL`, `SUPERTONIC_API_KEY`).

## A live voice agent (LiveKit or similar)

Goal: speak an LLM's reply with low time-to-first-audio and stop instantly when the user
interrupts.

- **Simplest: OpenAI-compatible TTS plugin.** Point the plugin at the server:
  `base_url="http://127.0.0.1:8787/v1"`, `model="supertonic-3"`, `voice="F1"`, any
  `api_key` when auth is off. The plugin calls `POST /v1/audio/speech`; use
  `response_format="pcm"` where the plugin lets you choose, so audio streams per sentence
  (24 kHz, 16-bit mono) at realtime priority with `SUPERTONIC_REALTIME_STEPS` (unless you
  pass `total_steps`). Compressed formats are rendered whole and limited to 20 000
  characters. This path waits for the plugin to send whole text, so first audio is one
  sentence of synthesis.
- **Lowest latency: the realtime WebSocket.** Stream the LLM's tokens with
  `input_text_buffer.append` as they arrive; each finished sentence is synthesised and
  returned immediately, without waiting for the rest of the reply. Send
  `input_text_buffer.commit` at the end of the reply to flush the last fragment.
- **Barge-in.** When the user starts talking, send `context.cancel` for the context that is
  speaking. The server stops synthesis, drops audio it has not sent yet and answers
  `context.cancelled`; no `delta` for that context follows. Use one `context_id` per agent
  turn so a cancelled turn never mixes with the next one; finished or cancelled contexts
  are forgotten as needed, so a long conversation never runs out of contexts.
- **Concurrency.** The server runs 4 workers on a 10-core machine and prioritises
  realtime sentences (and `pcm` speech) over other REST requests, which also cannot fill
  the queue that realtime work uses. On Apple M4 (see [benchmarks](benchmarks.md))
  first audio arrives in about 210 ms alone and about 410 ms (p95 under 500 ms) with 4
  simultaneous sessions. Size `SUPERTONIC_WORKERS` for your expected concurrent sessions.
- **Sample rate.** Ask for what your pipeline uses (`sample_rate=16000` or `24000`) so no
  client-side resampling is needed.
- **Deployment.** Run the server next to the agent on loopback. If the agent is remote,
  use an API key and a tunnel; see the README.

## A video narration pipeline that needs word timing

Goal: narrate a script and align captions or visuals to words.

1. Call `POST /v1/tts/timestamps` once per scene or paragraph with `response_format` set to
   `wav` (simplest to concatenate) or `mp3`. The response has the audio (`audio_base64`) and
   `words[]` / `segments[]` with `start_ms` and `end_ms` relative to the start of that
   audio.
2. Offset each scene's timings by the running total of the previous scenes' `duration_ms`
   when building a whole-video timeline.
3. **Timings are estimated, not measured.** They are distributed within each sentence
   from its synthesised duration, so they can drift by a fraction of a second inside a long
   sentence. Keep sentences short for tight sync, and snap caption cuts to `segments`
   boundaries, which are exact.
4. For Japanese, `timing_unit` is `character`: each item is one character.
5. Choose a voice by id and fail on error. An unknown voice returns `404 voice_not_found`
   and an unknown language `400 language_not_supported`; treat either as a hard failure
   rather than falling back to another voice.
6. Keep each request under 20 000 characters (one scene or paragraph at a time); longer
   text is refused with `400 input_too_long`.
7. Use `total_steps` 8 (the default) for final renders. Fewer steps are faster but the
   quality has not been evaluated.
