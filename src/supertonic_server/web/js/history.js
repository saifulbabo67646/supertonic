// Recent generations list (settings only; audio is never stored).

import { formatTime, h, replace } from "./dom.js";
import { clearHistory } from "./store.js";

const PREVIEW_CHARS = 140;

/**
 * Render the history panel.
 * @param {HTMLElement} root
 * @param {Array<object>} entries newest first
 * @param {(entry: object) => void} onRegenerate
 * @param {{voiceName: (id: string) => string, languageName: (code: string) => string}} [names]
 */
export function renderHistory(root, entries, onRegenerate, names = {}) {
  const voiceName = names.voiceName || ((id) => id);
  const languageName = names.languageName || ((code) => code);
  const head = h(
    "div",
    { class: "section-head" },
    h("h2", { id: "history-title", text: "Recent" }),
  );
  root.setAttribute("aria-labelledby", "history-title");
  if (!entries.length) {
    replace(
      root,
      head,
      h("p", {
        class: "empty",
        text: "Nothing yet. Each time you press Generate, it is listed here so you can make it again.",
      }),
    );
    return;
  }
  const clear = h("button", { type: "button", class: "btn ghost small", text: "Clear history" });
  clear.addEventListener("click", () => {
    clearHistory();
    renderHistory(root, [], onRegenerate, names);
  });
  head.append(clear);
  const list = h(
    "ol",
    { class: "history-list" },
    entries.map((entry) => {
      const text =
        entry.text.length > PREVIEW_CHARS ? `${entry.text.slice(0, PREVIEW_CHARS)}…` : entry.text;
      const btn = h("button", { type: "button", class: "btn small", text: "Make again" });
      btn.setAttribute("aria-label", `Make again: ${text.slice(0, 60)}`);
      btn.addEventListener("click", () => onRegenerate(entry));
      const speed = Number(entry.speed || 1.05).toFixed(2);
      return h(
        "li",
        {},
        h("p", { class: "history-text", text }),
        h(
          "div",
          { class: "history-meta" },
          h("span", { class: "chip", text: entry.voice ? voiceName(entry.voice) : "?" }),
          h("span", { class: "chip", text: languageName(entry.language || "en") }),
          h("span", { text: `speed ${speed}` }),
          h("time", {
            datetime: new Date(entry.timestamp).toISOString(),
            text: formatTime(entry.timestamp),
          }),
          btn,
        ),
      );
    }),
  );
  replace(root, head, list);
}
