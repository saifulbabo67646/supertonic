// Speak screen: script editor, voice/language/speed controls, generate, player and history.

import * as api from "./api.js";
import { finalizeWav, ObjectUrlSlot, playPreview } from "./audio.js";
import { getLanguages, getVoices, onVoicesChanged } from "./catalog.js";
import { fileStamp, h, replace } from "./dom.js";
import { renderHistory } from "./history.js";
import { buildControls, fillTags, fillVoices } from "./speak-controls.js";
import { addHistory, getHistory } from "./store.js";

const MAX_CHARS = 100_000;

const ui = {};
const resultSlot = new ObjectUrlSlot();
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
  if (entry.language) ui.language.value = entry.language;
  if (entry.speed) ui.speed.value = entry.speed;
  if (entry.steps) ui.steps.value = entry.steps;
  const fmt = ui.form.querySelector(
    `input[name=format][value="${entry.format === "mp3" ? "mp3" : "wav"}"]`,
  );
  fmt.checked = true;
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
    ui.status.set("Quality steps must be a whole number from 1 to 20.", "error");
    ui.steps.focus();
    return;
  }
  if (!s.voice) {
    ui.status.set("Pick a voice first.", "error");
    return;
  }
  busy = true;
  ui.generate.disabled = true;
  ui.generate.textContent = "Generating…";
  ui.status.set("Generating audio…", "busy");
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
    const url = resultSlot.set(blob);
    ui.player.src = url;
    ui.download.href = url;
    ui.download.download = `${s.voice}-${s.language}-${fileStamp(now)}.${s.format}`;
    ui.resultMeta.textContent = `${s.voice}, ${s.language}, speed ${s.speed.toFixed(2)}, ${s.format.toUpperCase()}`;
    ui.result.hidden = false;
    const secs = ((performance.now() - started) / 1000).toFixed(1);
    ui.status.set(`Generated in ${secs} s.`, "ok");
    renderHistory(ui.history, addHistory({ ...s, timestamp: now.getTime() }), onRegenerate);
    ui.player.play().catch(() => {});
  } catch (err) {
    ui.status.set(err.message, "error");
  } finally {
    busy = false;
    ui.generate.disabled = false;
    ui.generate.textContent = "Generate";
  }
}

function onRegenerate(entry) {
  ui.text.scrollIntoView({ block: "nearest" });
  if (!applySettings(entry)) {
    ui.status.set(`The voice "${entry.voice}" no longer exists. Pick another voice.`, "error");
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
    placeholder: "Type or paste what you want to hear.",
    "aria-describedby": "script-count script-keys",
  });
  ui.count = h("span", { id: "script-count", class: "count" });
  const sample = h("button", { type: "button", class: "btn ghost small", text: "Use sample" });
  ui.result = h("section", {
    class: "result panel",
    "aria-labelledby": "result-title",
    hidden: true,
  });
  ui.player = h("audio", { controls: true, preload: "auto" });
  ui.download = h("a", { class: "btn", href: "#", text: "Download" });
  ui.resultMeta = h("p", { class: "meta" });
  replace(
    ui.result,
    h("h2", { id: "result-title", text: "Latest take" }),
    ui.resultMeta,
    h("div", { class: "player-row" }, ui.player, ui.download),
  );
  ui.history = h("div", { class: "history" });

  ui.form = h(
    "form",
    { class: "speak-grid", novalidate: true },
    h(
      "div",
      { class: "script-panel" },
      h("label", { for: "script", class: "script-label", text: "Script" }),
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
  replace(
    root,
    h(
      "header",
      { class: "view-head" },
      h("h1", { id: "speak-title", text: "Speak" }),
      h("p", {
        text: "Write a script, choose a voice and language, and generate audio on this server.",
      }),
    ),
    ui.form,
    ui.result,
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
  sample.addEventListener("click", () => {
    const lang = languages.find((l) => l.code === ui.language.value);
    if (lang) ui.text.value = lang.sample;
    updateCount();
    ui.text.focus();
  });
  ui.preview.addEventListener("click", () =>
    playPreview(ui.voice.value, ui.language.value, ui.preview).catch((err) =>
      ui.status.set(err.message, "error"),
    ),
  );
  updateCount();
  renderHistory(ui.history, getHistory(), onRegenerate);
  onVoicesChanged(setVoices);
  load();
}

async function load() {
  try {
    const [langs, list] = await Promise.all([getLanguages(), getVoices()]);
    languages = langs;
    replace(
      ui.language,
      langs.map((l) => h("option", { value: l.code, text: `${l.name} (${l.code})` })),
    );
    ui.language.value = "en";
    setVoices(list);
    applyParams();
  } catch (err) {
    ui.status.set(`Could not load voices and languages: ${err.message}`, "error");
  }
}

let pendingParams = null;
function applyParams() {
  const voice = pendingParams?.get("voice");
  if (voice && allVoices.some((v) => v.id === voice)) {
    ui.tag.value = "";
    fillVoices(ui, allVoices);
    ui.voice.value = voice;
  }
  // Drop the one-shot parameter so a reload does not override later choices.
  if (voice) window.history.replaceState(null, "", "#/speak");
  pendingParams = null;
}

/** Called on every visit; `?voice=<id>` preselects a voice. */
export function show(params) {
  pendingParams = params;
  if (allVoices.length) applyParams();
}
