// Voices screen: library of preset and custom voices with preview, edit, export and delete;
// the entry point to building a new voice.

import * as api from "./api.js";
import { playPreview } from "./audio.js";
import { buildFacts, noBuilderCard } from "./build-copy.js";
import { getHealth, getLanguages, onVoicesChanged, refreshVoices } from "./catalog.js";
import { downloadBlob, h, replace, statusLine } from "./dom.js";
import { friendlyError } from "./errors.js";
import { buildImportForm } from "./voice-import.js";
import { confirmDelete, editForm } from "./voice-manage.js";

const ui = {};
let languages = [];
let voices = [];
let kindFilter = "all";
const notify = (text) => ui.status.set(text, "ok");
const fail = (err) => ui.status.set(friendlyError(err), "error");

function languageSelect(label) {
  const select = h(
    "select",
    { class: "compact", "aria-label": label },
    languages.filter((l) => l.code !== "na").map((l) => h("option", { value: l.code, text: l.name })),
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
      "aria-label": `Play a sample of ${voice.name}`,
      title: "Play a short sample",
    },
    h("span", { class: "play-glyph", "aria-hidden": "true" }),
  );
  play.addEventListener("click", () =>
    playPreview(voice.id, lang.value, play).catch(fail),
  );
  const use = h("a", {
    class: "btn small",
    href: `#/speak?voice=${encodeURIComponent(voice.id)}`,
    text: "Use in Speak",
  });
  const exp = h("button", {
    type: "button",
    class: "btn ghost small",
    text: "Download voice file",
    title: "Save this voice as a .json file, to back it up or add it to another Supertonic",
  });
  exp.setAttribute("aria-label", `Download the voice file for ${voice.name}`);
  exp.addEventListener("click", async () => {
    try {
      downloadBlob(await api.exportStyle(voice.id), `${voice.id}.json`);
      notify(`Downloaded the voice file for ${voice.name} (${voice.id}.json).`);
    } catch (err) {
      fail(err);
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
        text: voice.kind === "preset" ? "Built-in" : "Yours",
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
      text: "Rename or edit",
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
        text:
          "You have not made any voices yet. Press New voice to make one from a recording, " +
          "or add a voice file below.",
      }),
    );
  }
  replace(ui.list, cards);
  const custom = voices.filter((v) => v.kind === "custom").length;
  ui.count.textContent = `${voices.length - custom} built-in, ${custom} yours`;
}

function filterBar() {
  const options = [
    ["all", "All"],
    ["preset", "Built-in"],
    ["custom", "Your voices"],
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
        text:
          "Press ▶ to hear a voice in any language. Make a new voice from a recording, and " +
          "rename, download or delete the voices you made.",
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
  if (builder === "none") {
    const more = h(
      "details",
      { class: "no-builder-note" },
      h("summary", { text: "Why can't I make a new voice here?" }),
      noBuilderCard("voices-no-builder-title"),
    );
    replace(ui.build, more);
    return;
  }
  replace(
    ui.build,
    h(
      "div",
      { class: "row" },
      h("a", { class: "btn primary", href: "#/voices/new", text: "New voice" }),
      h("span", { class: "hint", text: "Make a voice from a recording of someone speaking." }),
    ),
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
    ui.status.set(`Could not load the voices. ${friendlyError(err)}`, "error");
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
