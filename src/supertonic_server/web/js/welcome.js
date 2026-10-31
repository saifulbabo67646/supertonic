// First-run welcome on the Speak screen: the three things you can do, in plain words.

import { h } from "./dom.js";
import { GUIDE_URL } from "./errors.js";
import { setWelcomeDismissed, welcomeDismissed } from "./store.js";

/**
 * The three things Studio does, for the welcome card. Counts come from the server.
 * @param {{voices: number, languages: number}} counts
 */
export function welcomeItems({ voices, languages }) {
  return [
    {
      title: "Speak",
      text:
        `Type any text, pick one of ${voices} voices and ${languages} languages, and press ` +
        "Generate to hear it. Download it as MP3 or WAV.",
      href: "#/speak",
    },
    {
      title: "Voices",
      text: "Listen to every voice, or make a new one from a short recording of someone speaking.",
      href: "#/voices",
    },
    {
      title: "Connect",
      text: "Use Supertonic from other apps, scripts and AI assistants such as Claude Code.",
      href: "#/connect",
    },
  ];
}

/**
 * The welcome card, or null when it was dismissed before.
 * @param {{voices: number, languages: number}} counts
 * @param {() => void} onSample fills in a sample sentence
 */
export function welcomeCard(counts, onSample) {
  if (welcomeDismissed()) return null;
  const sample = h("button", { type: "button", class: "btn primary small", text: "Try a sample" });
  const close = h("button", { type: "button", class: "btn ghost small", text: "Got it, hide this" });
  const card = h(
    "section",
    { class: "welcome panel", "aria-labelledby": "welcome-title" },
    h("h2", { id: "welcome-title", text: "Welcome to Supertonic" }),
    h("p", {
      class: "welcome-lead",
      text:
        "Supertonic turns text into natural speech. It runs on your own computer, so what you " +
        "type stays here. Here is what you can do:",
    }),
    h(
      "ol",
      { class: "welcome-list" },
      welcomeItems(counts).map((item) =>
        h(
          "li",
          {},
          h("a", { href: item.href, text: item.title }),
          h("span", { text: item.text }),
        ),
      ),
    ),
    h(
      "div",
      { class: "row" },
      sample,
      close,
      h("a", {
        class: "welcome-guide",
        href: GUIDE_URL,
        target: "_blank",
        rel: "noopener",
        text: "Read the beginner's guide",
      }),
    ),
  );
  sample.addEventListener("click", onSample);
  close.addEventListener("click", () => {
    setWelcomeDismissed();
    card.remove();
    document.getElementById("script")?.focus();
  });
  return card;
}
