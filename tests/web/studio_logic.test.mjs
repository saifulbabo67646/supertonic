// Unit tests for the Studio's pure modules (no DOM). Run by test_studio_logic.py via `node --test`.

import assert from "node:assert/strict";
import { test } from "node:test";

const JS = "../../src/supertonic_server/web/js";
const { friendlyError, friendlyJobError } = await import(`${JS}/errors.js`);
const { READING_TEXTS, readingText } = await import(`${JS}/reading-texts.js`);
const { snippets, DIR_PLACEHOLDER, KEY_PLACEHOLDER } = await import(`${JS}/connect-snippets.js`);
const { METHOD_HELP, METHOD_NAMES, duration, pitchWarning } = await import(`${JS}/build-copy.js`);

test("an unreachable server gets a sentence about the Supertonic window", () => {
  const text = friendlyError({ status: 0, message: "Could not reach the server (Failed to fetch)" });
  assert.match(text, /not responding/);
  assert.doesNotMatch(text, /Failed to fetch/);
});

test("recording problems are explained with what to do", () => {
  const short = friendlyError({
    status: 400,
    code: "invalid_reference_audio",
    message: "reference has 2.1 s of speech; need at least 3 s",
  });
  assert.match(short, /too little speech \(only 2\.1 seconds were found\)/);
  const silent = friendlyError({
    code: "invalid_reference_audio",
    message: "reference is 80% silence; at most 70% is allowed",
  });
  assert.match(silent, /mostly silence/);
  const long = friendlyError({
    code: "invalid_reference_audio",
    message: "reference has 75.0 s of speech; at most 60 s",
  });
  assert.match(long, /more than 60 seconds/);
});

test("known codes never show the raw code", () => {
  for (const code of ["voice_name_taken", "builder_unavailable", "not_ready", "invalid_style"]) {
    const text = friendlyError({ status: 400, code, message: "raw" });
    assert.ok(!text.includes(code), code);
    assert.ok(!text.includes("raw"), code);
  }
});

test("server errors keep the details after a plain sentence", () => {
  const text = friendlyError({ status: 500, code: "internal_error", message: "boom" });
  assert.match(text, /^Something went wrong inside Supertonic\./);
  assert.match(text, /\(Details: boom\)$/);
});

test("other client errors pass the server message through", () => {
  assert.equal(friendlyError({ status: 400, code: "invalid_request", message: "x" }), "x");
  // A message that merely mentions "busy" is not a busy server.
  const text = "Voice 'Busy Bee' not found";
  assert.equal(friendlyError({ status: 400, code: "invalid_request", message: text }), text);
});

test("a full queue says Supertonic is busy", () => {
  for (const err of [{ status: 503, code: "server_busy", message: "q" }, { status: 429 }]) {
    assert.match(friendlyError(err), /^Supertonic is busy right now\./);
  }
});

test("failed builds explain what happened", () => {
  assert.match(friendlyJobError(null), /did not finish/);
  assert.match(friendlyJobError({ code: "interrupted", message: "server restarted" }), /restarted/);
  assert.match(friendlyJobError({ code: "internal_error", message: "CUDA OOM" }), /Details: CUDA OOM/);
});

test("reading texts are long enough and fall back to English", () => {
  for (const [code, text] of Object.entries(READING_TEXTS)) {
    assert.ok(text.length >= 150, `${code} is ${text.length} characters`);
  }
  assert.deepEqual(readingText("de"), { text: READING_TEXTS.de, language: "de", fallback: false });
  assert.deepEqual(readingText("fi"), { text: READING_TEXTS.en, language: "en", fallback: true });
});

test("snippets without a key never mention one", () => {
  const { main, more } = snippets("http://127.0.0.1:8787", "Mia", false);
  for (const s of [...main, ...more]) assert.ok(!s.code.includes("SUPERTONIC_API_KEY"), s.id);
  const openai = main.find((s) => s.id === "openai");
  assert.match(openai.code, /base_url="http:\/\/127\.0\.0\.1:8787\/v1"/);
  assert.match(openai.code, /voice="Mia"/);
  const claude = main.find((s) => s.id === "claude-code");
  assert.equal(
    claude.code,
    "claude mcp add supertonic --scope user --env SUPERTONIC_BASE_URL=http://127.0.0.1:8787 " +
      `-- uv --directory ${DIR_PLACEHOLDER} run supertonic-mcp`,
  );
  const mcp = JSON.parse(main.find((s) => s.id === "mcp").code);
  assert.deepEqual(mcp.mcpServers.supertonic.args, [
    "--directory",
    DIR_PLACEHOLDER,
    "run",
    "supertonic-mcp",
  ]);
  assert.deepEqual(mcp.mcpServers.supertonic.env, { SUPERTONIC_BASE_URL: "http://127.0.0.1:8787" });
});

test("snippets with a key use the placeholder everywhere", () => {
  const { main, more } = snippets("https://tts.example.com", "Hugo", true);
  const claude = main.find((s) => s.id === "claude-code");
  assert.match(claude.code, new RegExp(`--env SUPERTONIC_API_KEY=${KEY_PLACEHOLDER} -- uv `));
  assert.ok(!claude.code.includes("\n"), "one line, so it pastes into any shell");
  const mcp = JSON.parse(main.find((s) => s.id === "mcp").code);
  assert.equal(mcp.mcpServers.supertonic.env.SUPERTONIC_API_KEY, KEY_PLACEHOLDER);
  const ws = more.find((s) => s.id === "ws");
  assert.ok(ws.code.startsWith("wss://tts.example.com/v1/audio/speech/websocket?voice=Hugo"));
  assert.match(more.find((s) => s.id === "curl").code, /Authorization: Bearer/);
});

test("every build method has a name and a help line", () => {
  assert.deepEqual(Object.keys(METHOD_HELP).sort(), Object.keys(METHOD_NAMES).sort());
  assert.equal(duration(3725), "1 h 02 min");
  assert.equal(duration(42), "42 s");
});

test("a built voice off its recording's pitch gets a plain warning", () => {
  const high = pitchWarning({ pitch_match: false, pitch_reference_hz: 129, pitch_voice_hz: 202 });
  assert.equal(
    high,
    "This voice sounds higher than your recording. " +
      "Try making it again with a longer, clearer recording.",
  );
  const low = pitchWarning({ pitch_match: false, pitch_reference_hz: 210, pitch_voice_hz: 120 });
  assert.match(low, /^This voice sounds lower than your recording\./);
  for (const build of [{ pitch_match: true }, { pitch_match: null }, {}, null, undefined]) {
    assert.equal(pitchWarning(build), null);
  }
});
