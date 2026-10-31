// Custom voice management: inline edit form and in-page delete confirmation.

import * as api from "./api.js";
import { refreshVoices } from "./catalog.js";
import { field, h, replace, statusLine } from "./dom.js";
import { friendlyError } from "./errors.js";

const parseTags = (raw) =>
  raw
    .split(",")
    .map((t) => t.trim())
    .filter(Boolean);

/**
 * Show the inline edit form for a custom voice inside `area`.
 * @param {(text: string) => void} notify reports success on the page
 */
export function editForm(voice, area, card, notify) {
  const name = h("input", { type: "text", required: true, maxlength: "120" });
  name.value = voice.name;
  const description = h("textarea", { rows: "2", maxlength: "2000" });
  description.value = voice.description;
  const tags = h("input", { type: "text" });
  tags.value = voice.tags.join(", ");
  const status = statusLine();
  const save = h("button", { type: "submit", class: "btn primary small", text: "Save changes" });
  const cancel = h("button", { type: "button", class: "btn ghost small", text: "Cancel" });
  const form = h(
    "form",
    { class: "inline-form", novalidate: true },
    field("Name", name),
    field("Description", description),
    field("Tags", tags, "Words to filter by, separated by commas."),
    status,
    h("div", { class: "row end" }, cancel, save),
  );
  cancel.addEventListener("click", () => {
    replace(area);
    card.querySelector("[data-action=edit]").focus();
  });
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (!name.value.trim()) {
      status.set("Give the voice a name.", "error");
      name.focus();
      return;
    }
    save.disabled = true;
    try {
      await api.updateVoice(voice.id, {
        name: name.value.trim(),
        description: description.value,
        tags: parseTags(tags.value),
      });
      notify(`Saved changes to ${name.value.trim()}.`);
      await refreshVoices();
    } catch (err) {
      status.set(friendlyError(err), "error");
      save.disabled = false;
    }
  });
  replace(area, form);
  name.focus();
}

/** Show the in-page delete confirmation for a custom voice inside `area`. */
export function confirmDelete(voice, area, card, notify) {
  const keep = h("button", { type: "button", class: "btn ghost small", text: "Keep voice" });
  const del = h("button", { type: "button", class: "btn danger small", text: "Delete voice" });
  const status = statusLine();
  const box = h(
    "div",
    { class: "confirm", role: "group", "aria-label": `Confirm deleting ${voice.name}` },
    h("p", {
      text:
        `Delete “${voice.name}” for good? It is removed from this server and cannot be ` +
        "brought back. To keep a copy, press Download voice file first.",
    }),
    status,
    h("div", { class: "row end" }, keep, del),
  );
  keep.addEventListener("click", () => {
    replace(area);
    card.querySelector("[data-action=delete]").focus();
  });
  del.addEventListener("click", async () => {
    del.disabled = true;
    try {
      await api.deleteVoice(voice.id);
      notify(`Deleted ${voice.name}.`);
      await refreshVoices();
      document.querySelector(".voice-grid")?.focus();
    } catch (err) {
      status.set(friendlyError(err), "error");
      del.disabled = false;
    }
  });
  replace(area, box);
  keep.focus();
}
