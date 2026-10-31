// "Import voice" form: upload a style JSON with a name, description, tags and source note.

import * as api from "./api.js";
import { field, h, statusLine } from "./dom.js";
import { friendlyError } from "./errors.js";

const MAX_BYTES = 2 * 1024 * 1024;

/**
 * Build the import section.
 * @param {(voice: object) => Promise<void>} onImported called with the created voice
 */
export function buildImportForm(onImported) {
  const file = h("input", { type: "file", accept: ".json,application/json", required: true });
  const name = h("input", { type: "text", required: true, maxlength: "120", autocomplete: "off" });
  const description = h("textarea", { rows: "2", maxlength: "2000" });
  const tags = h("input", { type: "text", autocomplete: "off" });
  const source = h("input", { type: "text", autocomplete: "off" });
  const submit = h("button", { type: "submit", class: "btn primary", text: "Add voice" });
  const status = statusLine();

  const form = h(
    "form",
    { class: "import-form", novalidate: true },
    field(
      "Voice file (.json)",
      file,
      "A file saved with “Download voice file”, from this or another Supertonic. Up to 2 MB.",
    ),
    field("Voice name", name),
    field("Description (optional)", description),
    field("Tags (optional)", tags, "Words to filter by, separated by commas, for example: narration, calm"),
    field(
      "Where is it from? (optional)",
      source,
      "For example: shared by Ana, made from her own voice. Helps you credit it later.",
    ),
    status,
    h("div", { class: "row end" }, submit),
  );

  file.addEventListener("change", () => {
    const chosen = file.files[0];
    if (chosen && !name.value.trim()) name.value = chosen.name.replace(/\.json$/i, "");
  });

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const chosen = file.files[0];
    if (!chosen) {
      status.set("Choose a voice file (.json) first.", "error");
      file.focus();
      return;
    }
    if (chosen.size > MAX_BYTES) {
      status.set("That file is larger than 2 MB, so it is not a voice file.", "error");
      file.focus();
      return;
    }
    if (!name.value.trim()) {
      status.set("Give the voice a name.", "error");
      name.focus();
      return;
    }
    const data = new FormData();
    data.append("file", chosen, chosen.name);
    data.append("name", name.value.trim());
    data.append("description", description.value);
    data.append("tags", tags.value);
    data.append("source_note", source.value);
    submit.disabled = true;
    status.set("Adding the voice…", "busy");
    try {
      const voice = await api.importVoice(data);
      form.reset();
      status.set(`Added ${voice.name}. It is now in the list above.`, "ok");
      await onImported(voice);
    } catch (err) {
      status.set(friendlyError(err), "error");
    } finally {
      submit.disabled = false;
    }
  });

  return h(
    "details",
    { class: "import panel" },
    h("summary", {}, h("h2", { class: "summary-title", text: "Add a voice from a file" })),
    h("p", {
      class: "hint",
      text:
        "Someone sent you a Supertonic voice file, or you saved one from another computer? " +
        "Add it here and it can be used everywhere: in Speak and in connected apps.",
    }),
    form,
  );
}
