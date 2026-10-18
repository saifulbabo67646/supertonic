// Speak screen controls: voice and tag pickers, language, speed and advanced options.

import { voiceLabel } from "./catalog.js";
import { field, h, replace, statusLine } from "./dom.js";

export const DEFAULT_SPEED = 1.05;
export const DEFAULT_STEPS = 8;

/**
 * Build the voice, language, speed and advanced controls; stores elements on `ui`.
 * @param {Record<string, any>} ui
 */
export function buildControls(ui) {
  ui.tag = h("select");
  ui.tagField = field("Filter by tag", ui.tag);
  ui.voice = h("select", { required: true });
  ui.preview = h(
    "button",
    {
      type: "button",
      class: "btn icon",
      "aria-label": "Preview selected voice",
      "aria-pressed": "false",
      title: "Preview voice",
    },
    h("span", { class: "play-glyph", "aria-hidden": "true" }),
  );
  const voiceField = field("Voice", ui.voice);
  voiceField.classList.add("with-action");
  voiceField.append(ui.preview);
  ui.language = h("select");
  ui.speed = h("input", {
    type: "range",
    min: "0.7",
    max: "2",
    step: "0.05",
    value: String(DEFAULT_SPEED),
  });
  ui.speedOut = h("output", { class: "range-value" });
  ui.speedOut.value = DEFAULT_SPEED.toFixed(2);
  const speedField = field("Speed", ui.speed, "0.70 is slowest, 2.00 is fastest.");
  speedField.querySelector("label").append(ui.speedOut);
  ui.steps = h("input", {
    type: "number",
    min: "1",
    max: "20",
    step: "1",
    value: String(DEFAULT_STEPS),
    inputmode: "numeric",
  });
  const formatSet = h(
    "fieldset",
    { class: "segmented" },
    h("legend", { text: "Format" }),
    ["wav", "mp3"].map((fmt) =>
      h(
        "label",
        {},
        h("input", { type: "radio", name: "format", value: fmt, checked: fmt === "wav" }),
        h("span", { text: fmt.toUpperCase() }),
      ),
    ),
  );
  const advanced = h(
    "details",
    { class: "advanced" },
    h("summary", { text: "Advanced" }),
    field("Quality steps", ui.steps, "1 to 20. More steps sound cleaner but take longer."),
    formatSet,
  );
  ui.generate = h("button", { type: "submit", class: "btn primary wide", text: "Generate" });
  ui.status = statusLine();
  return h(
    "div",
    { class: "controls panel" },
    ui.tagField,
    voiceField,
    field("Language", ui.language),
    speedField,
    advanced,
    ui.generate,
    ui.status,
  );
}

/** Fill the voice picker with voices matching the tag filter, keeping the selection. */
export function fillVoices(ui, allVoices) {
  const tag = ui.tag.value;
  const current = ui.voice.value;
  const shown = allVoices.filter((v) => !tag || v.tags.includes(tag));
  const groups = [
    ["Presets", shown.filter((v) => v.kind === "preset")],
    ["Custom voices", shown.filter((v) => v.kind === "custom")],
  ];
  replace(
    ui.voice,
    groups
      .filter(([, list]) => list.length)
      .map(([label, list]) =>
        h(
          "optgroup",
          { label },
          list.map((v) => h("option", { value: v.id, text: voiceLabel(v) })),
        ),
      ),
  );
  if (shown.some((v) => v.id === current)) ui.voice.value = current;
  ui.preview.disabled = shown.length === 0;
}

/** Fill the tag filter from all voices' tags; hidden when no voice has tags. */
export function fillTags(ui, allVoices) {
  const tags = [...new Set(allVoices.flatMap((v) => v.tags))].sort();
  const current = ui.tag.value;
  replace(
    ui.tag,
    h("option", { value: "", text: "All voices" }),
    tags.map((t) => h("option", { value: t, text: t })),
  );
  ui.tag.value = tags.includes(current) ? current : "";
  ui.tagField.hidden = tags.length === 0;
}
