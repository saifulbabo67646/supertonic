// New voice screen: reference clips, details, method and consent; build progress; recent builds.

import * as api from "./api.js";
import { createJobView } from "./build-job.js";
import {
  ACTIVE_STATES,
  LICENCE_TEXT,
  LICENCE_URL,
  METHOD_NAMES,
  METHODS,
  NO_BUILDER_TEXT,
  STATE_LABELS,
} from "./build-copy.js";
import { getHealth } from "./catalog.js";
import { field, formatTime, h, replace, statusLine } from "./dom.js";
import { buildClips } from "./voice-clips.js";

const ui = {};
let methods = [];
let available = false;
let visit = 0;
/** The "Build queued for …" note: which job it is about and its text (null when not shown). */
let queuedNote = null;

function methodField() {
  ui.methodHint = h("p", { class: "hint", id: "method-hint" });
  return h(
    "fieldset",
    { class: "methods", "aria-describedby": "method-hint" },
    h("legend", { text: "Method" }),
    METHODS.map(([value, label]) =>
      h(
        "label",
        { class: "choice" },
        h("input", { type: "radio", name: "method", value }),
        h("span", { text: label }),
      ),
    ),
    ui.methodHint,
  );
}

/** Enable only the methods the builder lists; prefer `accurate`. */
function applyMethods() {
  const radios = [...ui.form.querySelectorAll("input[name=method]")];
  for (const radio of radios) radio.disabled = !methods.includes(radio.value);
  const pick =
    radios.find((r) => !r.disabled && r.value === "accurate") || radios.find((r) => !r.disabled);
  if (pick && !radios.some((r) => r.checked && !r.disabled)) pick.checked = true;
  const off = METHODS.filter(([v]) => !methods.includes(v)).map(([v]) => METHOD_NAMES[v]);
  ui.methodHint.textContent = off.length
    ? `${off.join(" and ")} is not available on this server's builder.`
    : "Best match compares the result with the recording thousands of times. Quick draft is a fast first take.";
}

function buildForm() {
  ui.status = statusLine();
  ui.clips = buildClips((text) => ui.status.set(text, "error"));
  ui.name = h("input", { type: "text", required: true, maxlength: "100", autocomplete: "off" });
  ui.description = h("textarea", { rows: "2", maxlength: "500" });
  ui.tags = h("input", { type: "text", autocomplete: "off" });
  ui.source = h("input", { type: "text", required: true, autocomplete: "off" });
  ui.consent = h("input", { type: "checkbox", id: "consent", required: true });
  ui.submit = h("button", { type: "submit", class: "btn primary", text: "Build voice" });
  ui.form = h(
    "form",
    { class: "build-form", novalidate: true },
    ui.clips.el,
    field("Name", ui.name),
    field("Description", ui.description),
    field("Tags", ui.tags, "Separate tags with commas, for example: narration, calm"),
    field(
      "Where is this recording from?",
      ui.source,
      "Required. For example: my own voice, recorded today; or an interview with Ana, used with permission.",
    ),
    methodField(),
    h(
      "div",
      { class: "check" },
      ui.consent,
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
    ui.status,
    h("div", { class: "row end" }, ui.submit),
  );
  ui.form.addEventListener("submit", submit);
  return h(
    "section",
    { class: "panel build", "aria-labelledby": "build-title" },
    h("h2", { id: "build-title", text: "Recording and details" }),
    ui.form,
  );
}

function invalid(text, control) {
  ui.status.set(text, "error");
  control?.focus();
}

async function submit(e) {
  e.preventDefault();
  const problem = ui.clips.check();
  if (problem) return invalid(problem, ui.form.querySelector("#clip-input"));
  if (!ui.name.value.trim()) return invalid("Give the voice a name.", ui.name);
  if (!ui.source.value.trim()) {
    return invalid("Say where the recording is from.", ui.source);
  }
  if (!ui.consent.checked) {
    return invalid("Confirm that you have the speaker's permission.", ui.consent);
  }
  const method = ui.form.querySelector("input[name=method]:checked:not(:disabled)");
  if (!method) return invalid("This server's builder offers no build method.", null);
  const data = new FormData();
  for (const file of ui.clips.files()) data.append("files", file, file.name);
  data.append("name", ui.name.value.trim());
  data.append("description", ui.description.value);
  data.append("tags", ui.tags.value);
  data.append("source_note", ui.source.value.trim());
  data.append("consent", "true");
  data.append("method", method.value);
  ui.submit.disabled = true;
  ui.status.set("Uploading and checking the recording…", "busy");
  try {
    const job = await api.buildVoice(data);
    ui.form.reset();
    ui.clips.reset();
    applyMethods();
    queuedNote = { jobId: job.id, text: `Build queued for ${job.request.name}.` };
    ui.status.set(queuedNote.text, "ok");
    openJob(job, true);
    refreshJobs();
  } catch (err) {
    ui.status.set(err.message, "error");
  } finally {
    ui.submit.disabled = false;
  }
}

/** Drop the queued note once its job has left the queue (started, finished or cancelled). */
function clearQueuedNote(job) {
  if (!queuedNote || job.id !== queuedNote.jobId || job.state === "queued") return;
  if (ui.status.textContent === queuedNote.text) ui.status.clear();
  queuedNote = null;
}

function openJob(job, focus) {
  window.history.replaceState(null, "", `#/voices/new?job=${encodeURIComponent(job.id)}`);
  ui.job.track(job, focus);
  if (focus) ui.job.el.scrollIntoView({ block: "start" });
}

async function refreshJobs() {
  let list;
  try {
    list = await api.jobs(10);
  } catch (err) {
    replace(ui.jobs, h("p", { class: "status error", text: err.message }));
    return [];
  }
  if (!list.length) {
    replace(ui.jobs, h("p", { class: "empty", text: "No builds yet." }));
    return list;
  }
  replace(
    ui.jobs,
    h(
      "ul",
      { class: "job-list" },
      list.map((job) => {
        const view = h("button", { type: "button", class: "btn ghost small", text: "View" });
        view.setAttribute("aria-label", `View build of ${job.request.name}`);
        view.addEventListener("click", () => openJob(job, true));
        return h(
          "li",
          {},
          h("span", { class: "job-name", text: job.request.name }),
          h("span", { class: `badge state-${job.state}`, text: STATE_LABELS[job.state] }),
          h("span", {
            class: "meta",
            text: `${METHOD_NAMES[job.request.method] || job.request.method}, ${formatTime(Date.parse(job.created_at))}`,
          }),
          view,
        );
      }),
    ),
  );
  return list;
}

/** Build the screen once. */
export function mount(root) {
  // A file dropped just outside the drop zone must not make the browser open it and leave the page.
  const guard = (e) => {
    if (!root.hidden && e.dataTransfer?.types?.includes("Files")) e.preventDefault();
  };
  window.addEventListener("dragover", guard);
  window.addEventListener("drop", guard);
  ui.job = createJobView((job) => {
    clearQueuedNote(job);
    refreshJobs();
  });
  ui.jobs = h("div", { class: "jobs" });
  ui.unavailable = h("p", { class: "notice panel", hidden: true, text: NO_BUILDER_TEXT });
  ui.body = h(
    "div",
    { class: "new-voice-body", hidden: true },
    ui.job.el,
    buildForm(),
    h(
      "section",
      { class: "recent", "aria-labelledby": "recent-title" },
      h("div", { class: "section-head" }, h("h2", { id: "recent-title", text: "Recent builds" })),
      ui.jobs,
    ),
  );
  replace(
    root,
    h(
      "header",
      { class: "view-head" },
      h("a", { class: "back", href: "#/voices", text: "← Voices" }),
      h("h1", { id: "new-voice-title", text: "New voice" }),
      h("p", {
        text: "Build a custom voice from a short recording of one speaker. Building runs on the server's GPU; you can leave this page and come back.",
      }),
    ),
    ui.unavailable,
    ui.body,
  );
}

/** Called on every visit; `?job=<id>` shows that build. */
export async function show(params) {
  const mine = ++visit;
  let health;
  try {
    health = await getHealth();
  } catch (err) {
    replace(ui.unavailable, `Could not reach the server: ${err.message}`);
    ui.unavailable.hidden = false;
    return;
  }
  if (mine !== visit) return;
  available = health.builder !== "none";
  ui.unavailable.hidden = available;
  ui.body.hidden = !available;
  if (!available) return;
  methods = health.builder_detail?.methods || [];
  applyMethods();
  const list = await refreshJobs();
  if (mine !== visit) return;
  const wanted = params.get("job");
  if (wanted) {
    try {
      const job = await api.job(wanted);
      if (mine === visit) openJob(job, false);
    } catch (err) {
      if (mine === visit) ui.status.set(err.message, "error");
    }
  } else if (ui.job.current()) {
    ui.job.resume();
  } else {
    const active = list.find((j) => ACTIVE_STATES.has(j.state));
    if (active) openJob(active, false);
  }
}

/** Leaving the screen: stop polling and any recording. */
export function hide() {
  visit++;
  ui.job.pause();
  ui.clips.cancel();
}
