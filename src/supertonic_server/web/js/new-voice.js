// New voice screen: the step-by-step form, build progress (steps 4 and 5) and recent builds.

import * as api from "./api.js";
import { createJobView } from "./build-job.js";
import { ACTIVE_STATES, METHOD_NAMES, noBuilderCard, STATE_LABELS } from "./build-copy.js";
import { getHealth } from "./catalog.js";
import { formatTime, h, replace } from "./dom.js";
import { friendlyError } from "./errors.js";
import { buildVoiceForm } from "./new-voice-form.js";

const ui = {};
let available = false;
let visit = 0;
/** The "Build queued for …" note: which job it is about and its text (null when not shown). */
let queuedNote = null;

function queued(job) {
  queuedNote = {
    jobId: job.id,
    text: `Building ${job.request.name} has started. Progress is shown at the top of this page.`,
  };
  ui.form.status.set(queuedNote.text, "ok");
  openJob(job, true);
  refreshJobs();
}

/** Drop the queued note once its job has left the queue (started, finished or cancelled). */
function clearQueuedNote(job) {
  if (!queuedNote || job.id !== queuedNote.jobId || job.state === "queued") return;
  if (ui.form.status.textContent === queuedNote.text) ui.form.status.clear();
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
    replace(ui.jobs, h("p", { class: "status error", text: friendlyError(err) }));
    return [];
  }
  if (!list.length) {
    replace(ui.jobs, h("p", { class: "empty", text: "Voices you build are listed here." }));
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
  ui.unavailable = h("div", { hidden: true }, noBuilderCard("no-builder-title"));
  ui.form = buildVoiceForm(queued);
  ui.body = h(
    "div",
    { class: "new-voice-body", hidden: true },
    ui.job.el,
    ui.form.el,
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
        text:
          "Make a new voice from a short recording of one person speaking. Building takes " +
          "from about 15 minutes to 1½ hours; you can leave this page and come back.",
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
    replace(ui.unavailable, h("p", { class: "notice panel", text: friendlyError(err) }));
    ui.unavailable.hidden = false;
    return;
  }
  if (mine !== visit) return;
  available = health.builder !== "none";
  ui.unavailable.hidden = available;
  ui.body.hidden = !available;
  if (!available) return;
  ui.form.setMethods(health.builder_detail?.methods || []);
  const list = await refreshJobs();
  if (mine !== visit) return;
  const wanted = params.get("job");
  if (wanted) {
    try {
      const job = await api.job(wanted);
      if (mine === visit) openJob(job, false);
    } catch (err) {
      if (mine === visit) ui.form.status.set(friendlyError(err), "error");
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
  ui.form.cancel();
}
