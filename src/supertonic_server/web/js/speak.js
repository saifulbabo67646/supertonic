// Speak screen: script editor, voice/language/speed controls, generate, player and history.

import * as api from "./api.js";
import { finalizeWav, playPreview } from "./audio.js";
import { getLanguages, getVoices, onVoicesChanged } from "./catalog.js";
import { h, replace } from "./dom.js";
import { friendlyError } from "./errors.js";
import { renderHistory } from "./history.js";
import { buildControls, fillTags, fillVoices, showVoiceHint } from "./speak-controls.js";
import { createResult } from "./speak-result.js";
import { addHistory, getHistory } from "./store.js";
import { welcomeCard } from "./welcome.js";

const MAX_CHARS = 100_000;

const ui = {};
let languages = [];
let allVoices = [];
let busy = false;

function updateCount() {
  const n = ui.text.value.length;
  ui.count.textContent = `${n.toLocaleString()} / ${MAX_CHARS.toLocaleString()} characters`;
  ui.count.classList.toggle("over", n > MAX_CHARS);
}

function setVoices(list) {
  allVoices = list;
  fillTags(ui, allVoices);
  fillVoices(ui, allVoices);
}

function settings() {
  return {
    text: ui.text.value,
    voice: ui.voice.value,
    language: ui.language.value,
    speed: Number(ui.speed.value),
    steps: Number(ui.steps.value),
    format: ui.form.querySelector("input[name=format]:checked").value,
  };
}

function applySettings(entry) {
  ui.text.value = entry.text;
  const listed = () => [...ui.voice.options].some((o) => o.value === entry.voice);
  if (!listed()) {
    ui.tag.value = "";
    fillVoices(ui, allVoices);
  }
  const found = listed();
  if (found) ui.voice.value = entry.voice;
  showVoiceHint(ui);
  if (entry.language) ui.language.value = entry.language;
  if (entry.speed) ui.speed.value = entry.speed;
  if (entry.steps) ui.steps.value = entry.steps;
  const fmt = ui.form.querySelector(
    `input[name=format][value="${entry.format === "wav" ? "wav" : "mp3"}"]`,
  );
  fmt.checked = true;
  ui.showFormatHint();
  ui.speedOut.value = Number(ui.speed.value).toFixed(2);
  updateCount();
  return found;
}

async function generate() {
  if (busy) return;
  const s = settings();
  if (!s.text.trim()) {
    ui.status.set("Write something to speak first.", "error");
    ui.text.focus();
    return;
  }
  if (!Number.isInteger(s.steps) || s.steps < 1 || s.steps > 20) {
    ui.status.set("Quality steps must be a whole number from 1 to 20 (open Advanced).", "error");
    ui.steps.closest("details").open = true;
    ui.steps.focus();
    return;
  }
  if (!s.voice) {
    ui.status.set("Pick a voice first.", "error");
    ui.voice.focus();
    return;
  }
  busy = true;
  ui.generate.disabled = true;
  ui.generate.textContent = "Generating…";
  ui.status.set("Making your audio…", "busy");
  const started = performance.now();
  try {
    let blob = await api.speech({
      input: s.text,
      voice: s.voice,
      language: s.language,
      speed: s.speed,
      total_steps: s.steps,
      response_format: s.format,
    });
    if (s.format === "wav") blob = await finalizeWav(blob);
    const now = new Date();
    ui.result.show({
      blob,
      format: s.format,
      voiceName: voiceName(s.voice),
      language: s.language,
      languageName: languageName(s.language),
      speed: s.speed,
      date: now,
    });
    const secs = ((performance.now() - started) / 1000).toFixed(1);
    ui.status.set(`Done in ${secs} seconds. It is playing below.`, "ok");
    showHistory(addHistory({ ...s, timestamp: now.getTime() }));
  } catch (err) {
    ui.status.set(friendlyError(err), "error");
  } finally {
    busy = false;
    ui.generate.disabled = false;
    ui.generate.textContent = "Generate";
  }
}

const voiceName = (id) => allVoices.find((v) => v.id === id)?.name || id;
const languageName = (code) => languages.find((l) => l.code === code)?.name || code;

function showHistory(entries) {
  renderHistory(ui.history, entries, onRegenerate, { voiceName, languageName });
}

function useSample() {
  const lang = languages.find((l) => l.code === ui.language.value);
  if (lang) ui.text.value = lang.sample;
  updateCount();
  ui.text.focus();
}

function onRegenerate(entry) {
  ui.text.scrollIntoView({ block: "nearest" });
  if (!applySettings(entry)) {
    ui.status.set(`The voice "${entry.voice}" no longer exists. Pick another voice.`, "error");
    ui.voice.focus();
    return;
  }
  generate();
}

/** Build the screen once. */
export function mount(root) {
  ui.text = h("textarea", {
    class: "script",
    rows: "9",
    maxlength: String(MAX_CHARS),
    placeholder: "Type or paste what you want to hear: a sentence, a paragraph or a whole article.",
    "aria-describedby": "script-count script-keys",
  });
  ui.count = h("span", { id: "script-count", class: "count" });
  const sample = h("button", {
    type: "button",
    class: "btn ghost small",
    text: "Try a sample sentence",
  });
  ui.result = createResult();
  ui.history = h("div", { class: "history" });

  ui.form = h(
    "form",
    { class: "speak-grid", novalidate: true },
    h(
      "div",
      { class: "script-panel" },
      h("label", { for: "script", class: "script-label", text: "Text to speak" }),
      ui.text,
      h(
        "div",
        { class: "script-foot" },
        ui.count,
        h("span", { id: "script-keys", class: "hint", text: "Ctrl or Cmd + Enter to generate" }),
        sample,
      ),
    ),
    buildControls(ui),
  );
  ui.text.id = "script";
  ui.welcome = h("div", { class: "welcome-slot" });
  replace(
    root,
    h(
      "header",
      { class: "view-head" },
      h("h1", { id: "speak-title", text: "Speak" }),
      h("p", {
        text: "Type some text, pick a voice and a language, then press Generate to hear it.",
      }),
    ),
    ui.welcome,
    ui.form,
    ui.result.el,
    ui.history,
  );

  ui.text.addEventListener("input", updateCount);
  ui.text.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
      e.preventDefault();
      generate();
    }
  });
  ui.form.addEventListener("submit", (e) => {
    e.preventDefault();
    generate();
  });
  ui.speed.addEventListener("input", () => (ui.speedOut.value = Number(ui.speed.value).toFixed(2)));
  ui.tag.addEventListener("change", () => fillVoices(ui, allVoices));
  sample.addEventListener("click", useSample);
  ui.preview.addEventListener("click", () =>
    playPreview(ui.voice.value, ui.language.value, ui.preview).catch((err) =>
      ui.status.set(friendlyError(err), "error"),
    ),
  );
  updateCount();
  showHistory(getHistory());
  onVoicesChanged((list) => {
    setVoices(list);
    showHistory(getHistory());
  });
  load();
}

async function load() {
  try {
    const [langs, list] = await Promise.all([getLanguages(), getVoices()]);
    languages = langs;
    replace(
      ui.language,
      langs.map((l) => h("option", { value: l.code, text: l.name })),
    );
    ui.language.value = "en";
    setVoices(list);
    showHistory(getHistory());
    const counts = { voices: list.length, languages: langs.filter((l) => l.code !== "na").length };
    replace(
      ui.welcome,
      welcomeCard(counts, () => {
        if (!ui.text.value.trim()) useSample();
        generate();
      }),
    );
    applyParams();
  } catch (err) {
    ui.status.set(`Could not load the voices and languages. ${friendlyError(err)}`, "error");
  }
}

let pendingParams = null;
function applyParams() {
  const voice = pendingParams?.get("voice");
  // `?voice=` takes an id or a name, in the API's order: exact id, built-in name, id in any
  // capitalisation, then custom voice name.
  const low = voice?.toLowerCase();
  const wanted =
    voice &&
    (allVoices.find((v) => v.id === voice) ??
      allVoices.find((v) => v.kind === "preset" && v.name.toLowerCase() === low) ??
      allVoices.find((v) => v.id.toLowerCase() === low) ??
      allVoices.find((v) => v.name.toLowerCase() === low));
  if (wanted) {
    ui.tag.value = "";
    fillVoices(ui, allVoices);
    ui.voice.value = wanted.id;
    showVoiceHint(ui);
  }
  const language = pendingParams?.get("language");
  if (language && languages.some((l) => l.code === language)) ui.language.value = language;
  // Drop the one-shot parameters so a reload does not override later choices.
  if (voice || language) window.history.replaceState(null, "", "#/speak");
  pendingParams = null;
}

/** Called on every visit; `?voice=<id or name>&language=<code>` preselect a voice and language. */
export function show(params) {
  pendingParams = params;
  if (allVoices.length) applyParams();
}
