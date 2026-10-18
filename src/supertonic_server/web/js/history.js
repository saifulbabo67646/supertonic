// Recent generations list (settings only; audio is never stored).

import { formatTime, h, replace } from "./dom.js";
import { clearHistory } from "./store.js";

const PREVIEW_CHARS = 140;

/**
 * Render the history panel.
 * @param {HTMLElement} root
 * @param {Array<object>} entries newest first
 * @param {(entry: object) => void} onRegenerate
 */
export function renderHistory(root, entries, onRegenerate) {
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
        text: "Your last 20 generations in this browser appear here, ready to regenerate.",
      }),
    );
    return;
  }
  const clear = h("button", { type: "button", class: "btn ghost small", text: "Clear history" });
  clear.addEventListener("click", () => {
    clearHistory();
    renderHistory(root, [], onRegenerate);
  });
  head.append(clear);
  const list = h(
    "ol",
    { class: "history-list" },
    entries.map((entry) => {
      const text =
        entry.text.length > PREVIEW_CHARS ? `${entry.text.slice(0, PREVIEW_CHARS)}…` : entry.text;
      const btn = h("button", { type: "button", class: "btn small", text: "Regenerate" });
      btn.setAttribute("aria-label", `Regenerate: ${text.slice(0, 60)}`);
      btn.addEventListener("click", () => onRegenerate(entry));
      const speed = Number(entry.speed || 1.05).toFixed(2);
      return h(
        "li",
        {},
        h("p", { class: "history-text", text }),
        h(
          "div",
          { class: "history-meta" },
          h("span", { class: "chip", text: entry.voice || "?" }),
          h("span", { class: "chip", text: entry.language || "en" }),
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
