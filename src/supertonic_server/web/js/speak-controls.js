// Speak screen controls: voice and tag pickers, language, speed and advanced options.

import { voiceLabel } from "./catalog.js";
import { field, h, replace, statusLine } from "./dom.js";
import { FORMATS } from "./speak-result.js";

export const DEFAULT_SPEED = 1.05;
export const DEFAULT_STEPS = 8;
export const DEFAULT_FORMAT = "mp3";

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
      "aria-label": "Play a short sample of the selected voice",
      "aria-pressed": "false",
      title: "Play a short sample of this voice",
    },
    h("span", { class: "play-glyph", "aria-hidden": "true" }),
  );
  const voiceField = field("Voice", ui.voice);
  voiceField.classList.add("with-action");
  ui.voiceHint = h("p", { class: "hint", id: "voice-hint", "aria-live": "polite" });
  ui.voice.setAttribute("aria-describedby", ui.voiceHint.id);
  voiceField.append(ui.preview, ui.voiceHint);
  ui.voice.addEventListener("change", () => showVoiceHint(ui));
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
  const speedField = field(
    "Speed",
    ui.speed,
    `Starts at ${DEFAULT_SPEED.toFixed(2)}. Move left to slow down, right to speed up.`,
  );
  speedField.querySelector("label").append(ui.speedOut);
  ui.steps = h("input", {
    type: "number",
    min: "1",
    max: "20",
    step: "1",
    value: String(DEFAULT_STEPS),
    inputmode: "numeric",
  });
  ui.formatHint = h("p", { class: "hint", id: "format-hint" });
  const formatSet = h(
    "fieldset",
    { class: "segmented", "aria-describedby": "format-hint" },
    h("legend", { text: "File type" }),
    FORMATS.map((f) =>
      h(
        "label",
        {},
        h("input", {
          type: "radio",
          name: "format",
          value: f.value,
          checked: f.value === DEFAULT_FORMAT,
        }),
        h("span", { text: f.label }),
      ),
    ),
  );
  const showFormatHint = () => {
    const chosen = formatSet.querySelector("input:checked")?.value;
    const f = FORMATS.find((x) => x.value === chosen) || FORMATS[0];
    ui.formatHint.textContent = `${f.label}: ${f.hint}.`;
  };
  formatSet.addEventListener("change", showFormatHint);
  showFormatHint();
  ui.showFormatHint = showFormatHint;
  const advanced = h(
    "details",
    { class: "advanced" },
    h("summary", { text: "Advanced" }),
    field(
      "Quality steps",
      ui.steps,
      "How many passes are used to polish the sound, 1 to 20. More sounds a little cleaner " +
        "but takes longer; 8 is a good balance.",
    ),
  );
  ui.generate = h("button", { type: "submit", class: "btn primary wide", text: "Generate" });
  ui.status = statusLine();
  return h(
    "div",
    { class: "controls panel" },
    ui.tagField,
    voiceField,
    field("Language", ui.language, "The language your text is written in."),
    speedField,
    h("div", { class: "field" }, formatSet, ui.formatHint),
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
    ["Built-in voices", shown.filter((v) => v.kind === "preset")],
    ["Your voices", shown.filter((v) => v.kind === "custom")],
  ];
  replace(
    ui.voice,
    groups
      .filter(([, list]) => list.length)
      .map(([label, list]) =>
        h(
          "optgroup",
          { label },
          list.map((v) =>
            h("option", { value: v.id, text: voiceLabel(v), title: v.description || "" }),
          ),
        ),
      ),
  );
  if (shown.some((v) => v.id === current)) ui.voice.value = current;
  ui.preview.disabled = shown.length === 0;
  showVoiceHint(ui);
}

/** Show the selected voice's description under the picker (empty when it has none). */
export function showVoiceHint(ui) {
  const option = ui.voice.selectedOptions[0];
  ui.voiceHint.textContent = option ? option.title : "";
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
