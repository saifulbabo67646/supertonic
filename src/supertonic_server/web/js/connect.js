// Connect screen: base URL, auth status and copy-ready client snippets for this server.

import { BASE_URL } from "./api.js";
import { getHealth, getVoices } from "./catalog.js";
import { copyButton, h, replace, statusLine } from "./dom.js";
import { askForKey } from "./keydialog.js";
import { getApiKey, setApiKey } from "./store.js";

const ui = {};
const KEY_PLACEHOLDER = "your-api-key";

/** Build every snippet for `origin`, `voice` and whether the server requires a key. */
export function snippets(origin, voice, auth) {
  const wsOrigin = origin.replace(/^http/, "ws");
  const curlAuth = auth ? `  -H "Authorization: Bearer $SUPERTONIC_API_KEY" \\\n` : "";
  const pyKey = auth ? 'os.environ["SUPERTONIC_API_KEY"]' : '"not-needed"';
  const pyImport = auth ? "import os\n\n" : "";
  const body = JSON.stringify({
    model: "supertonic-3",
    input: "Hello from Supertonic.",
    voice,
    response_format: "wav",
  });
  const wsQuery = new URLSearchParams({ voice, language: "en" });
  const wsUrl = `${wsOrigin}/v1/audio/speech/websocket?${wsQuery}${auth ? `&api_key=${KEY_PLACEHOLDER}` : ""}`;
  const mcp = {
    mcpServers: {
      supertonic: {
        command: "supertonic-mcp",
        env: { SUPERTONIC_BASE_URL: origin, SUPERTONIC_API_KEY: auth ? KEY_PLACEHOLDER : "" },
      },
    },
  };
  return [
    {
      id: "curl",
      title: "curl",
      note: "Writes a WAV file to the current directory.",
      code:
        `curl ${origin}/v1/audio/speech \\\n` +
        curlAuth +
        `  -H "Content-Type: application/json" \\\n` +
        `  -d '${body}' \\\n` +
        `  -o speech.wav`,
    },
    {
      id: "openai",
      title: "OpenAI Python SDK",
      note: "Any OpenAI-compatible client works; point it at /v1.",
      code:
        `${pyImport}from openai import OpenAI\n\n` +
        `client = OpenAI(base_url="${origin}/v1", api_key=${pyKey})\n\n` +
        `response = client.audio.speech.create(\n` +
        `    model="supertonic-3",\n` +
        `    voice="${voice}",\n` +
        `    input="Hello from Supertonic.",\n` +
        `    response_format="wav",\n` +
        `)\n` +
        `response.write_to_file("speech.wav")`,
    },
    {
      id: "livekit",
      title: "LiveKit Agents",
      note: "Uses the OpenAI plugin's TTS with this server as the backend.",
      code:
        `${pyImport}from livekit.plugins import openai\n\n` +
        `tts = openai.TTS(\n` +
        `    base_url="${origin}/v1",\n` +
        `    api_key=${pyKey},\n` +
        `    model="supertonic-3",\n` +
        `    voice="${voice}",\n` +
        `)`,
    },
    {
      id: "ws",
      title: "Realtime WebSocket",
      note: auth
        ? "Send Authorization: Bearer when your client can set headers; browsers use ?api_key= instead."
        : "Stream text in with input_text_buffer.append, then input_text_buffer.commit.",
      code: wsUrl,
    },
    {
      id: "mcp",
      title: "MCP server for agents",
      note: "Add to your MCP client's configuration (for example Claude Desktop).",
      code: JSON.stringify(mcp, null, 2),
    },
  ];
}

function snippetBlock(s) {
  const titleId = `snippet-${s.id}`;
  return h(
    "section",
    { class: "snippet", "aria-labelledby": titleId },
    h(
      "div",
      { class: "snippet-head" },
      h("h2", { id: titleId, text: s.title }),
      copyButton(() => s.code, "Copy"),
    ),
    h("p", { class: "hint", text: s.note }),
    h("pre", { tabindex: "0", "aria-label": `${s.title} snippet` }, h("code", { text: s.code })),
  );
}

function keyControls(auth) {
  const saved = Boolean(getApiKey());
  const text = auth
    ? saved
      ? "This server requires an API key. One is saved in this browser."
      : "This server requires an API key. None is saved in this browser yet."
    : "This server does not require an API key.";
  const buttons = [];
  if (auth || saved) {
    const set = h("button", {
      type: "button",
      class: "btn small",
      text: saved ? "Change key" : "Enter key",
    });
    set.addEventListener("click", async () => {
      const key = await askForKey();
      if (key) {
        setApiKey(key);
        ui.status.set("Key saved in this browser.", "ok");
        renderKey(auth);
      }
    });
    buttons.push(set);
  }
  if (saved) {
    const forget = h("button", { type: "button", class: "btn ghost small", text: "Forget key" });
    forget.addEventListener("click", () => {
      setApiKey("");
      ui.status.set("Key removed from this browser.", "ok");
      renderKey(auth);
    });
    buttons.push(forget);
  }
  return [h("p", { text }), h("div", { class: "row" }, buttons)];
}

function renderKey(auth) {
  replace(ui.key, keyControls(auth));
}

/** Build the screen once. */
export function mount(root) {
  ui.status = statusLine();
  ui.key = h("div", { class: "key-box" });
  ui.snippets = h("div", { class: "snippets" });
  const base = h("code", { class: "base-url", text: BASE_URL });
  replace(
    root,
    h(
      "header",
      { class: "view-head" },
      h("h1", { id: "connect-title", text: "Connect" }),
      h("p", { text: "Use this server from code, agents and voice pipelines." }),
    ),
    h(
      "div",
      { class: "connect-top panel" },
      h(
        "div",
        {},
        h("h2", { text: "Base URL" }),
        h(
          "div",
          { class: "row" },
          base,
          copyButton(() => BASE_URL, "Copy URL"),
        ),
      ),
      h("div", {}, h("h2", { text: "API key" }), ui.key),
      h(
        "div",
        { class: "connect-stop" },
        h("h2", { text: "Stopping the server" }),
        h("p", {
          text:
            "Supertonic runs in the window that opened when you started it. To stop it, close " +
            "that window (or press Ctrl+C in it). To start it again, open Start Supertonic again.",
        }),
      ),
    ),
    ui.status,
    ui.snippets,
  );
}

/** Refresh auth state and snippets on every visit. */
export async function show() {
  try {
    const info = await getHealth();
    let voice = "F1";
    try {
      const list = await getVoices();
      if (list.length && !list.some((v) => v.id === voice)) voice = list[0].id;
    } catch {
      // Keep the default voice when the list needs a key that is not set yet.
    }
    renderKey(info.auth);
    replace(ui.snippets, snippets(BASE_URL, voice, info.auth).map(snippetBlock));
  } catch (err) {
    ui.status.set(`Could not reach the server: ${err.message}`, "error");
  }
}
