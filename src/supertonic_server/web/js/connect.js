// Connect screen: the addresses other apps need, the API key in plain words, copy-ready snippets.

import { BASE_URL } from "./api.js";
import { getHealth, getVoices } from "./catalog.js";
import { snippets } from "./connect-snippets.js";
import { copyButton, h, replace, statusLine } from "./dom.js";
import { friendlyError } from "./errors.js";
import { askForKey } from "./keydialog.js";
import { getApiKey, setApiKey } from "./store.js";

const ui = {};

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

/** A labelled value with a copy button. */
function copyRow(label, value, hint) {
  return h(
    "div",
    { class: "copy-row" },
    h("h2", { text: label }),
    h(
      "div",
      { class: "row" },
      h("code", { class: "base-url", text: value }),
      copyButton(() => value, "Copy"),
    ),
    hint ? h("p", { class: "hint", text: hint }) : null,
  );
}

function keyControls(auth) {
  const saved = Boolean(getApiKey());
  const what =
    "An API key is a password that apps send with every request, so that only people you " +
    "trust can use the server.";
  const text = auth
    ? `${what} This server requires one: use the key it was started with (SUPERTONIC_API_KEY). ` +
      (saved ? "It is saved in this browser." : "It is not saved in this browser yet.")
    : `${what} This server does not need one, because only this computer can reach it. If ` +
      "an app insists on a key, type anything, for example not-needed.";
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
  return [h("p", { text }), buttons.length ? h("div", { class: "row" }, buttons) : null];
}

function renderKey(auth) {
  replace(ui.key, keyControls(auth));
}

/** Build the screen once. */
export function mount(root) {
  ui.status = statusLine();
  ui.key = h("div", { class: "key-box" });
  ui.snippets = h("div", { class: "snippets" });
  ui.more = h("div", { class: "snippets" });
  replace(
    root,
    h(
      "header",
      { class: "view-head" },
      h("h1", { id: "connect-title", text: "Connect" }),
      h("p", {
        text:
          "Use Supertonic from other apps, scripts and AI assistants. Most apps that support " +
          "OpenAI text-to-speech work with it: give them the details below.",
      }),
    ),
    h(
      "div",
      { class: "connect-top panel" },
      copyRow(
        "Base URL",
        `${BASE_URL}/v1`,
        "Paste this where an app asks for an “OpenAI base URL”, “API base” or “endpoint”. " +
          "Use supertonic-3 as the model and a voice name such as Mia.",
      ),
      copyRow("Server address", BASE_URL, "The address of this page, for MCP and other tools."),
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
    h(
      "details",
      { class: "more-snippets" },
      h("summary", { text: "More examples for developers" }),
      ui.more,
    ),
  );
}

/** Refresh auth state and snippets on every visit. */
export async function show() {
  try {
    const info = await getHealth();
    let voice = "Mia";
    try {
      const list = await getVoices();
      const preset = list.find((v) => v.kind === "preset");
      if (list.length && !list.some((v) => v.name === voice)) voice = (preset || list[0]).name;
    } catch {
      // Keep the default voice when the list needs a key that is not set yet.
    }
    renderKey(info.auth);
    const { main, more } = snippets(BASE_URL, voice, info.auth);
    replace(ui.snippets, main.map(snippetBlock));
    replace(ui.more, more.map(snippetBlock));
  } catch (err) {
    ui.status.set(friendlyError(err), "error");
  }
}
