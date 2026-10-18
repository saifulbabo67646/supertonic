// "Import voice" form: upload a style JSON with a name, description, tags and source note.

import * as api from "./api.js";
import { field, h, statusLine } from "./dom.js";

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
  const submit = h("button", { type: "submit", class: "btn primary", text: "Import voice" });
  const status = statusLine();

  const form = h(
    "form",
    { class: "import-form", novalidate: true },
    field(
      "Style JSON file",
      file,
      "A Supertonic 3 voice style, for example one exported from this page. Up to 2 MB.",
    ),
    field("Name", name),
    field("Description", description),
    field("Tags", tags, "Separate tags with commas, for example: narration, calm"),
    field("Source note", source, "Where the voice came from, so you can credit or trace it later."),
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
      status.set("Choose a style JSON file to import.", "error");
      file.focus();
      return;
    }
    if (chosen.size > MAX_BYTES) {
      status.set("That file is larger than 2 MB, the limit for a style file.", "error");
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
    status.set("Importing…", "busy");
    try {
      const voice = await api.importVoice(data);
      form.reset();
      status.set(`Imported ${voice.name} as ${voice.id}.`, "ok");
      await onImported(voice);
    } catch (err) {
      status.set(err.message, "error");
    } finally {
      submit.disabled = false;
    }
  });

  return h(
    "section",
    { class: "import panel", "aria-labelledby": "import-title" },
    h("h2", { id: "import-title", text: "Import voice" }),
    h("p", {
      class: "hint",
      text: "Add a custom voice from a style JSON file. It is stored on this server and available to every client.",
    }),
    form,
  );
}
