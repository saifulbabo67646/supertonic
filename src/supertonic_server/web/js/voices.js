// Voices screen: library of preset and custom voices with preview, edit, export and delete;
// the entry point to building a new voice.

import * as api from "./api.js";
import { playPreview } from "./audio.js";
import { buildFacts, NO_BUILDER_TEXT } from "./build-copy.js";
import { getHealth, getLanguages, onVoicesChanged, refreshVoices } from "./catalog.js";
import { downloadBlob, h, replace, statusLine } from "./dom.js";
import { buildImportForm } from "./voice-import.js";
import { confirmDelete, editForm } from "./voice-manage.js";

const ui = {};
let languages = [];
let voices = [];
let kindFilter = "all";
const notify = (text) => ui.status.set(text, "ok");

function languageSelect(label) {
  const select = h(
    "select",
    { class: "compact", "aria-label": label },
    languages.map((l) =>
      h("option", { value: l.code, text: l.code === "na" ? "auto" : l.code, title: l.name }),
    ),
  );
  select.value = "en";
  return select;
}

function card(voice) {
  const area = h("div", { class: "card-extra" });
  const lang = languageSelect(`Preview language for ${voice.name}`);
  const play = h(
    "button",
    {
      type: "button",
      class: "btn icon",
      "aria-pressed": "false",
      "aria-label": `Preview ${voice.name}`,
    },
    h("span", { class: "play-glyph", "aria-hidden": "true" }),
  );
  play.addEventListener("click", () =>
    playPreview(voice.id, lang.value, play).catch((err) => ui.status.set(err.message, "error")),
  );
  const use = h("a", {
    class: "btn small",
    href: `#/speak?voice=${encodeURIComponent(voice.id)}`,
    text: "Use in Speak",
  });
  const exp = h("button", { type: "button", class: "btn ghost small", text: "Export" });
  exp.setAttribute("aria-label", `Export ${voice.name} style JSON`);
  exp.addEventListener("click", async () => {
    try {
      downloadBlob(await api.exportStyle(voice.id), `${voice.id}.json`);
    } catch (err) {
      ui.status.set(err.message, "error");
    }
  });
  const manage = h("div", { class: "manage" }, exp);
  const actions = h(
    "div",
    { class: "card-actions" },
    h("div", { class: "preview-group" }, play, lang),
    use,
    manage,
  );
  const article = h(
    "article",
    { class: `voice-card ${voice.kind}`, "data-voice-id": voice.id, tabindex: "-1" },
    h(
      "div",
      { class: "card-head" },
      h("h3", { text: voice.name }),
      h("span", {
        class: `badge ${voice.kind}`,
        text: voice.kind === "preset" ? "Preset" : "Custom",
      }),
    ),
    h(
      "p",
      { class: "voice-id" },
      voice.name !== voice.id ? h("code", { text: voice.id }) : null,
      voice.gender ? h("span", { text: voice.gender }) : null,
    ),
    voice.description ? h("p", { class: "description", text: voice.description }) : null,
    voice.tags.length
      ? h(
          "ul",
          { class: "tags", "aria-label": "Tags" },
          voice.tags.map((t) => h("li", { class: "chip", text: t })),
        )
      : null,
    voice.source_note ? h("p", { class: "hint", text: `Source: ${voice.source_note}` }) : null,
    voice.build ? buildFacts(voice.build) : null,
    actions,
    area,
  );
  if (voice.kind === "custom") {
    const edit = h("button", {
      type: "button",
      class: "btn ghost small",
      "data-action": "edit",
      text: "Edit",
    });
    const del = h("button", {
      type: "button",
      class: "btn ghost small danger-text",
      "data-action": "delete",
      text: "Delete",
    });
    edit.addEventListener("click", () => editForm(voice, area, article, notify));
    del.addEventListener("click", () => confirmDelete(voice, area, article, notify));
    manage.prepend(edit);
    manage.append(del);
  }
  return article;
}

function render() {
  const shown = voices.filter((v) => kindFilter === "all" || v.kind === kindFilter);
  const cards = shown.map(card);
  if (kindFilter === "custom" && !shown.length) {
    cards.unshift(
      h("p", {
        class: "empty",
        text: "No custom voices yet. Build one from a recording, or import a style JSON below.",
      }),
    );
  }
  replace(ui.list, cards);
  const custom = voices.filter((v) => v.kind === "custom").length;
  ui.count.textContent = `${voices.length - custom} presets, ${custom} custom`;
}

function filterBar() {
  const options = [
    ["all", "All"],
    ["preset", "Presets"],
    ["custom", "Custom"],
  ];
  const set = h(
    "fieldset",
    { class: "segmented" },
    h("legend", { class: "visually-hidden", text: "Show" }),
    options.map(([value, label]) => {
      const input = h("input", {
        type: "radio",
        name: "kind",
        value,
        checked: value === kindFilter,
      });
      input.addEventListener("change", () => {
        kindFilter = value;
        render();
      });
      return h("label", {}, input, h("span", { text: label }));
    }),
  );
  ui.count = h("p", { class: "meta" });
  ui.filter = set;
  return h("div", { class: "toolbar" }, set, ui.count);
}

/** Build the screen once. */
export function mount(root) {
  ui.status = statusLine();
  ui.build = h("div", { class: "build-entry" });
  ui.list = h("div", { class: "voice-grid", tabindex: "-1", "aria-label": "Voice library" });
  const imported = async (voice) => {
    if (kindFilter === "preset") {
      kindFilter = "all";
      ui.filter.querySelector("input[value=all]").checked = true;
    }
    await refreshVoices();
  };
  replace(
    root,
    h(
      "header",
      { class: "view-head" },
      h("h1", { id: "voices-title", text: "Voices" }),
      h("p", {
        text: "Preview the built-in voices, build new ones from a recording, and manage custom voices.",
      }),
      ui.build,
    ),
    filterBar(),
    ui.status,
    ui.list,
    buildImportForm(imported),
  );
  onVoicesChanged((list) => {
    voices = list;
    render();
  });
}

/** "New voice" when the server has a builder; otherwise how to enable one. */
async function renderBuildEntry() {
  let builder = "none";
  try {
    builder = (await getHealth()).builder;
  } catch {
    // The status line already reports an unreachable server.
  }
  replace(
    ui.build,
    builder === "none"
      ? h("p", { class: "hint", text: NO_BUILDER_TEXT })
      : h("a", { class: "btn primary", href: "#/voices/new", text: "New voice" }),
  );
}

/** Scroll to and focus the card for `voiceId` (from a "voice card" link). */
function focusCard(voiceId) {
  const target = [...ui.list.querySelectorAll(".voice-card")].find(
    (el) => el.dataset.voiceId === voiceId,
  );
  if (!target) return;
  for (const el of ui.list.querySelectorAll(".voice-card.highlight")) {
    el.classList.remove("highlight");
  }
  target.classList.add("highlight");
  target.scrollIntoView({ block: "center" });
  target.focus({ preventScroll: true });
}

/** Refresh on every visit; `?voice=<id>` scrolls to that voice's card. */
export async function show(params) {
  renderBuildEntry();
  try {
    // Always refetch: voices may have been built or imported elsewhere (MCP, REST, other tabs).
    const [langs, list] = await Promise.all([getLanguages(), refreshVoices()]);
    languages = langs;
    voices = list;
    render();
  } catch (err) {
    ui.status.set(`Could not load voices: ${err.message}`, "error");
    return;
  }
  const wanted = params?.get("voice");
  if (wanted) {
    if (kindFilter === "preset" && voices.some((v) => v.id === wanted && v.kind === "custom")) {
      kindFilter = "all";
      ui.filter.querySelector("input[value=all]").checked = true;
      render();
    }
    focusCard(wanted);
    window.history.replaceState(null, "", "#/voices");
  }
}
