// Recording tips for a new voice, with a passage to read aloud in the chosen language.

import { getLanguages } from "./catalog.js";
import { field, h, replace } from "./dom.js";
import { readingText } from "./reading-texts.js";

export const TIPS = [
  "Find a quiet room: no music, TV or other people talking.",
  "Keep the microphone close and at the same distance the whole time.",
  "Only one person should speak: the voice you want to copy.",
  "Talk naturally for 30 to 60 seconds. Reading the text below works well.",
];

/** Build the tips box; the passage language starts as English and follows the picker. */
export function buildTips() {
  const select = h("select", { class: "compact" });
  const passage = h("blockquote", { class: "reading-text", lang: "en" });
  const note = h("p", { class: "hint" });
  let names = {};

  function show() {
    const chosen = select.value || "en";
    const { text, language, fallback } = readingText(chosen);
    passage.textContent = text;
    passage.lang = language;
    note.textContent = fallback
      ? `There is no text in ${names[chosen] || chosen} here yet. Read this English text, or ` +
        `read anything you like in ${names[chosen] || chosen} for 30 to 60 seconds.`
      : "";
  }

  getLanguages()
    .then((langs) => {
      const usable = langs.filter((l) => l.code !== "na");
      names = Object.fromEntries(usable.map((l) => [l.code, l.name]));
      replace(
        select,
        usable.map((l) => h("option", { value: l.code, text: l.name })),
      );
      select.value = "en";
      show();
    })
    .catch(() => {
      // Without the language list, keep the English passage.
      select.hidden = true;
    });
  select.addEventListener("change", show);
  show();

  return h(
    "aside",
    { class: "tips", "aria-labelledby": "tips-title" },
    h("h3", { id: "tips-title", text: "Tips for a good recording" }),
    h(
      "ul",
      {},
      TIPS.map((t) => h("li", { text: t })),
    ),
    field("Text to read in", select),
    passage,
    note,
  );
}
