// Copy-ready snippets for the Connect screen. Pure module (no DOM), so it can be unit-tested.

export const KEY_PLACEHOLDER = "your-api-key";
/** Shown where the folder Supertonic was installed in goes; the browser cannot know it. */
export const DIR_PLACEHOLDER = "/path/to/supertonic";

/**
 * The main snippets (shown first) and the developer extras.
 * @param {string} origin e.g. "http://127.0.0.1:8787"
 * @param {string} voice a voice name or id, e.g. "Mia"
 * @param {boolean} auth whether the server requires an API key
 * @returns {{main: Array<Snippet>, more: Array<Snippet>}}
 * @typedef {{id: string, title: string, note: string, code: string}} Snippet
 */
export function snippets(origin, voice, auth) {
  const wsOrigin = origin.replace(/^http/, "ws");
  const curlAuth = auth ? `  -H "Authorization: Bearer $SUPERTONIC_API_KEY" \\\n` : "";
  const pyKey = auth ? 'os.environ["SUPERTONIC_API_KEY"]' : '"not-needed"';
  const pyImport = auth ? "import os\n\n" : "";
  const body = JSON.stringify({
    model: "supertonic-3",
    input: "Hello from Supertonic.",
    voice,
    response_format: "mp3",
  });
  const wsQuery = new URLSearchParams({ voice, language: "en" });
  const wsUrl = `${wsOrigin}/v1/audio/speech/websocket?${wsQuery}${auth ? `&api_key=${KEY_PLACEHOLDER}` : ""}`;
  const env = { SUPERTONIC_BASE_URL: origin };
  if (auth) env.SUPERTONIC_API_KEY = KEY_PLACEHOLDER;
  const mcp = {
    mcpServers: {
      supertonic: {
        command: "uv",
        args: ["--directory", DIR_PLACEHOLDER, "run", "supertonic-mcp"],
        env,
      },
    },
  };
  const claudeKey = auth ? `  --env SUPERTONIC_API_KEY=${KEY_PLACEHOLDER} \\\n` : "";
  const replaceDir = `Replace ${DIR_PLACEHOLDER} with the folder you put Supertonic in.`;
  const main = [
    {
      id: "openai",
      title: "OpenAI-compatible apps (Python)",
      note:
        "Anything that works with OpenAI text-to-speech works with Supertonic: point it at the " +
        "base URL above. This example saves speech.mp3.",
      code:
        `${pyImport}from openai import OpenAI\n\n` +
        `client = OpenAI(base_url="${origin}/v1", api_key=${pyKey})\n\n` +
        `response = client.audio.speech.create(\n` +
        `    model="supertonic-3",\n` +
        `    voice="${voice}",\n` +
        `    input="Hello from Supertonic.",\n` +
        `    response_format="mp3",\n` +
        `)\n` +
        `response.write_to_file("speech.mp3")`,
    },
    {
      id: "claude-code",
      title: "Claude Code",
      note:
        `Run this once in a terminal so Claude Code can speak with your voices. ${replaceDir} ` +
        `Then ask Claude, for example: “Say hello with the ${voice} voice.”`,
      code:
        `claude mcp add supertonic \\\n` +
        `  --env SUPERTONIC_BASE_URL=${origin} \\\n` +
        claudeKey +
        `  -- uv --directory ${DIR_PLACEHOLDER} run supertonic-mcp`,
    },
    {
      id: "mcp",
      title: "Other AI assistants (MCP)",
      note:
        "For Claude Desktop, Cursor and other apps that support MCP: add this to their MCP " +
        `settings. ${replaceDir}`,
      code: JSON.stringify(mcp, null, 2),
    },
  ];
  const more = [
    {
      id: "curl",
      title: "curl (command line)",
      note: "Saves speech.mp3 in the current folder.",
      code:
        `curl ${origin}/v1/audio/speech \\\n` +
        curlAuth +
        `  -H "Content-Type: application/json" \\\n` +
        `  -d '${body}' \\\n` +
        `  -o speech.mp3`,
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
  ];
  return { main, more };
}
