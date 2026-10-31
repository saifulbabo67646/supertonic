// New voice form, in three numbered steps: 1 recording, 2 name and permission, 3 build type.

import * as api from "./api.js";
import {
  LICENCE_TEXT,
  LICENCE_URL,
  METHOD_HELP,
  METHOD_NAMES,
  METHODS,
} from "./build-copy.js";
import { field, h, statusLine } from "./dom.js";
import { friendlyError } from "./errors.js";
import { buildClips } from "./voice-clips.js";
import { buildTips } from "./voice-tips.js";

/** A numbered step: a heading with its number, then the content. */
function step(number, id, title, ...children) {
  return h(
    "section",
    { class: "step", "aria-labelledby": id },
    h(
      "h2",
      { id, class: "step-title" },
      h("span", { class: "step-num", "aria-hidden": "true", text: String(number) }),
      h("span", { class: "visually-hidden", text: `Step ${number}: ` }),
      title,
    ),
    ...children,
  );
}

/**
 * Build the form.
 * @param {(job: object) => void} onQueued called with the new job after a successful submit
 * @returns {{el: HTMLElement, setMethods: (methods: string[]) => void, cancel: () => void,
 *   status: ReturnType<typeof statusLine>}}
 */
export function buildVoiceForm(onQueued) {
  const status = statusLine();
  const clips = buildClips((text) => status.set(text, "error"));
  const name = h("input", { type: "text", required: true, maxlength: "100", autocomplete: "off" });
  const description = h("textarea", { rows: "2", maxlength: "500" });
  const tags = h("input", { type: "text", autocomplete: "off" });
  const source = h("input", { type: "text", required: true, autocomplete: "off" });
  const consent = h("input", { type: "checkbox", id: "consent", required: true });
  const submit = h("button", { type: "submit", class: "btn primary", text: "Build voice" });
  const methodHint = h("p", { class: "hint", id: "method-hint" });
  let methods = [];

  const methodSet = h(
    "fieldset",
    { class: "methods", "aria-describedby": "method-hint" },
    h("legend", { class: "visually-hidden", text: "Build type" }),
    METHODS.map(([value, label]) =>
      h(
        "label",
        { class: "choice" },
        h("input", { type: "radio", name: "method", value }),
        h(
          "span",
          { class: "choice-text" },
          h("span", { class: "choice-label", text: label }),
          h("span", { class: "hint", text: METHOD_HELP[value] }),
        ),
      ),
    ),
    methodHint,
  );

  const form = h(
    "form",
    { class: "build-form", novalidate: true },
    step(1, "step-recording", "Record or upload the voice", buildTips(), clips.el),
    step(
      2,
      "step-details",
      "Name it and confirm permission",
      field("Voice name", name, "How it appears in the voice list, for example: Grandpa Joe."),
      field(
        "Where is this recording from?",
        source,
        "For example: my own voice, recorded today; or an interview with Ana, used with permission.",
      ),
      h(
        "div",
        { class: "check" },
        consent,
        h("label", {
          for: "consent",
          text: "I have the speaker's permission to create and use this voice",
        }),
      ),
      h(
        "p",
        { class: "hint licence" },
        `${LICENCE_TEXT} `,
        h("a", { href: LICENCE_URL, target: "_blank", rel: "noopener", text: "Read the licence" }),
        ".",
      ),
      h(
        "details",
        { class: "more-details" },
        h("summary", { text: "More details (optional)" }),
        field("Description", description, "A note for yourself, for example: warm, calm reader."),
        field("Tags", tags, "Words to filter by, separated by commas, for example: narration, calm"),
      ),
    ),
    step(3, "step-method", "Choose how to build it", methodSet),
    status,
    h("div", { class: "row end" }, submit),
  );

  function applyMethods() {
    const radios = [...form.querySelectorAll("input[name=method]")];
    for (const radio of radios) radio.disabled = !methods.includes(radio.value);
    const pick =
      radios.find((r) => !r.disabled && r.value === "accurate") || radios.find((r) => !r.disabled);
    if (pick && !radios.some((r) => r.checked && !r.disabled)) pick.checked = true;
    const off = METHODS.filter(([v]) => !methods.includes(v)).map(([v]) => METHOD_NAMES[v]);
    methodHint.textContent = off.length
      ? `${off.join(" and ")} is not available on this server's voice builder.`
      : "Times are for a typical NVIDIA graphics card. You can leave this page while it builds.";
  }

  function invalid(text, control) {
    status.set(text, "error");
    control?.focus();
  }

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const problem = clips.check();
    if (problem) return invalid(problem, form.querySelector("#clip-input"));
    if (!name.value.trim()) return invalid("Give the voice a name (step 2).", name);
    if (!source.value.trim()) {
      return invalid("Say where the recording is from (step 2).", source);
    }
    if (!consent.checked) {
      return invalid("Tick the box to confirm you have the speaker's permission.", consent);
    }
    const method = form.querySelector("input[name=method]:checked:not(:disabled)");
    if (!method) return invalid("This server's voice builder offers no build type.", null);
    const data = new FormData();
    for (const file of clips.files()) data.append("files", file, file.name);
    data.append("name", name.value.trim());
    data.append("description", description.value);
    data.append("tags", tags.value);
    data.append("source_note", source.value.trim());
    data.append("consent", "true");
    data.append("method", method.value);
    submit.disabled = true;
    status.set("Sending and checking the recording…", "busy");
    try {
      const job = await api.buildVoice(data);
      form.reset();
      clips.reset();
      applyMethods();
      onQueued(job);
    } catch (err) {
      status.set(friendlyError(err), "error");
    } finally {
      submit.disabled = false;
    }
  });

  return {
    el: h(
      "section",
      { class: "panel build", "aria-label": "New voice form" },
      form,
    ),
    status,
    setMethods(next) {
      methods = next;
      applyMethods();
    },
    cancel: clips.cancel,
  };
}
