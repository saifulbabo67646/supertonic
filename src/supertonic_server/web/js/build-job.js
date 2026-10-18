// Build progress view: polls one job, shows stage, steps, ETA and loss; Finish now, Cancel, Try it.

import * as api from "./api.js";
import {
  ACTIVE_STATES,
  duration,
  FINISHING_LABELS,
  METHOD_NAMES,
  STAGE_LABELS,
  STATE_LABELS,
} from "./build-copy.js";
import { loadResult, resultNodes } from "./build-result.js";
import { h, replace, statusLine } from "./dom.js";

const POLL_MS = 2000;
const MAX_BACKOFF_MS = 30_000;
/** Timbre samples kept for the ETA: a sliding window, so speed changes show up. */
const ETA_WINDOW = 20;

const parseTime = (iso) => (iso ? Date.parse(iso) : NaN);

/**
 * Seconds left in the timbre stage from (step, time) samples, or null while there are fewer
 * than two distinct steps to measure the time per step.
 * @param {Array<{step: number, at: number}>} samples oldest first
 */
export function estimateSecondsLeft(samples, total) {
  if (samples.length < 2) return null;
  const first = samples[0];
  const last = samples[samples.length - 1];
  const steps = last.step - first.step;
  if (steps <= 0 || !(total > last.step)) return null;
  const perStep = (last.at - first.at) / 1000 / steps;
  return perStep > 0 ? perStep * (total - last.step) : null;
}

function stat(label) {
  const dd = h("dd", { text: "—" });
  const row = h("div", {}, h("dt", { text: label }), dd);
  row.value = dd;
  return row;
}

/**
 * Create the job view.
 * @param {(job: object) => void} onChange called when a job's state changes
 * @returns {{el: HTMLElement, track: (job: object, focus?: boolean) => void,
 *   pause: () => void, resume: () => void, current: () => object|null}}
 */
export function createJobView(onChange) {
  const title = h("h2", { id: "job-title", tabindex: "-1" });
  const badge = h("span", { class: "badge" });
  const meta = h("p", { class: "meta" });
  const stage = h("p", { class: "job-stage", "aria-live": "polite" });
  const detail = h("p", { class: "hint" });
  const bar = h("progress", { max: "1", value: "0", "aria-labelledby": "job-step" });
  const stepText = h("p", { class: "meta", id: "job-step" });
  const progressWrap = h("div", { class: "job-progress" }, bar, stepText);
  const left = stat("Time left");
  const loss = stat("Loss");
  const elapsed = stat("Elapsed");
  const stats = h("dl", { class: "facts" }, left, loss, elapsed);
  const finish = h("button", {
    type: "button",
    class: "btn primary",
    text: "Finish now",
    "aria-describedby": "finish-hint",
  });
  const finishHint = h("span", {
    class: "hint",
    id: "finish-hint",
    text: "Stop and keep the best result so far",
  });
  const finishGroup = h("div", { class: "finish-group" }, finish, finishHint);
  const cancel = h("button", { type: "button", class: "btn ghost danger-text", text: "Cancel" });
  const confirm = h("div", { class: "confirm", role: "group", "aria-label": "Confirm cancel" });
  const actions = h("div", { class: "row job-actions" }, finishGroup, cancel);
  const result = h("div", { class: "job-result" });
  const status = statusLine();
  const el = h(
    "section",
    { class: "job panel", "aria-labelledby": "job-title", hidden: true },
    h("div", { class: "card-head" }, title, badge),
    meta,
    stage,
    detail,
    progressWrap,
    stats,
    actions,
    confirm,
    result,
    status,
  );

  let job = null;
  let samples = [];
  let timer = 0;
  let ticker = 0;
  let token = 0;
  let paused = true;
  let resultFor = "";
  let failures = 0;
  let focusResult = false;

  const halt = () => {
    clearTimeout(timer);
    clearInterval(ticker);
    timer = ticker = 0;
  };

  function schedule() {
    clearTimeout(timer);
    if (paused || !job || !ACTIVE_STATES.has(job.state)) return;
    const mine = token;
    // Back off on errors (2, 4, 8 … up to 30 s); back to 2 s after a success.
    const delay = failures ? Math.min(MAX_BACKOFF_MS, POLL_MS * 2 ** failures) : POLL_MS;
    timer = setTimeout(async () => {
      try {
        const next = await api.job(job.id);
        if (mine === token) {
          if (failures) status.clear();
          failures = 0;
          update(next);
        }
      } catch (err) {
        if (mine === token) {
          failures++;
          const wait = Math.min(MAX_BACKOFF_MS, POLL_MS * 2 ** failures) / 1000;
          status.set(
            `Could not refresh the build: ${err.message}. Retrying in ${wait} s.`,
            "error",
          );
        }
      }
      if (mine === token) schedule();
    }, delay);
  }

  function tickElapsed() {
    const start = parseTime(job.started_at);
    const end = job.finished_at ? parseTime(job.finished_at) : Date.now();
    elapsed.value.textContent = Number.isNaN(start) ? "—" : duration((end - start) / 1000);
  }

  function update(next) {
    const before = job?.state;
    // A control that is about to disappear must not take the keyboard focus with it.
    const focusedAction = actions.contains(document.activeElement);
    const focusedFinish = finishGroup.contains(document.activeElement);
    job = next;
    const p = job.progress;
    const active = ACTIVE_STATES.has(job.state);
    title.textContent = job.request.name;
    badge.textContent = STATE_LABELS[job.state] || job.state;
    badge.className = `badge state-${job.state}`;
    meta.textContent = `${METHOD_NAMES[job.request.method] || job.request.method}, on the ${job.builder} builder`;
    let stageText = "";
    if (job.state === "queued") stageText = "Waiting for the builder to be free…";
    else if (job.state === "running" && job.stopping) {
      // Finish now ends the timbre stage only; the rhythm match and saving still follow.
      stageText = FINISHING_LABELS[p?.stage] || "Finishing: keeping the best result so far…";
    } else if (job.state === "running") {
      stageText = p ? STAGE_LABELS[p.stage] || p.stage : "Starting…";
    }
    // Only touch the live region when the text changes, so each poll is not announced.
    if (stage.textContent !== stageText) stage.textContent = stageText;
    detail.textContent = active && p ? p.message : "";
    const steps = p && p.step != null && p.total;
    progressWrap.hidden = !(active && steps);
    if (steps) {
      bar.max = p.total;
      bar.value = p.step;
      stepText.textContent = `Step ${p.step.toLocaleString()} of ${p.total.toLocaleString()}`;
    }
    if (p && p.stage === "timbre" && p.step != null) {
      const at = parseTime(p.at);
      const last = samples[samples.length - 1];
      if (!last || p.step > last.step) samples.push({ step: p.step, at });
      if (samples.length > ETA_WINDOW) samples.shift();
    }
    const timbre = job.state === "running" && p?.stage === "timbre" && !job.stopping;
    const secs = estimateSecondsLeft(samples, p?.total);
    left.hidden = !timbre;
    left.value.textContent = secs === null ? "estimating…" : `about ${duration(secs)}`;
    loss.hidden = !(active && p && typeof p.loss === "number");
    if (p && typeof p.loss === "number") loss.value.textContent = p.loss.toFixed(4);
    tickElapsed();
    stats.hidden = job.state === "queued";
    actions.hidden = !active;
    finishGroup.hidden = !timbre;
    if (!active) replace(confirm);
    if ((focusedAction && actions.hidden) || (focusedFinish && finishGroup.hidden)) {
      // Park focus on the title; if the build then succeeds, it moves on to Try it.
      focusResult = true;
      title.focus();
    }
    if (job.state === "failed") status.set(job.error?.message || "The build failed.", "error");
    else if (job.state === "cancelled") status.set("This build was cancelled.", "info");
    else if (!active) status.clear();
    if (job.state === "succeeded" && resultFor !== job.id) showResult(job);
    clearInterval(ticker);
    ticker = job.state === "running" && !paused ? setInterval(tickElapsed, 1000) : 0;
    if (before !== undefined && before !== job.state) onChange(job);
  }

  async function showResult(done) {
    resultFor = done.id;
    replace(result, h("p", { text: `${done.request.name} is ready.` }));
    if (!done.voice_id) return;
    const data = await loadResult(done.voice_id);
    if (data.error) status.set(data.error, "error");
    if (job?.id !== done.id) return;
    const { nodes, tryIt } = resultNodes(done, data);
    replace(result, nodes);
    if (focusResult && document.activeElement === title) tryIt.focus();
    focusResult = false;
  }

  async function act(button, call) {
    button.disabled = true;
    try {
      update(await call(job.id));
    } catch (err) {
      status.set(err.message, "error");
    } finally {
      button.disabled = false;
    }
  }

  finish.addEventListener("click", () => act(finish, api.finishJob));
  cancel.addEventListener("click", () => {
    const keep = h("button", { type: "button", class: "btn ghost small", text: "Keep building" });
    const yes = h("button", { type: "button", class: "btn danger small", text: "Cancel build" });
    keep.addEventListener("click", () => {
      replace(confirm);
      cancel.focus();
    });
    yes.addEventListener("click", async () => {
      await act(yes, api.cancelJob);
      replace(confirm);
      title.focus();
    });
    replace(
      confirm,
      h("p", { text: "Cancel this build? Its progress is lost and no voice is saved." }),
      h("div", { class: "row end" }, keep, yes),
    );
    keep.focus();
  });

  return {
    el,
    /** Show `next` and poll it while it is active. */
    track(next, focus = false) {
      token++;
      halt();
      if (!job || job.id !== next.id) {
        samples = [];
        failures = 0;
        focusResult = false;
        resultFor = "";
        replace(result);
        replace(confirm);
        status.clear();
        job = null;
      }
      el.hidden = false;
      paused = false;
      update(next);
      schedule();
      if (focus) title.focus();
    },
    /** Stop polling (leaving the screen). */
    pause() {
      paused = true;
      token++;
      halt();
    },
    /** Refresh the tracked job now and poll again (returning to the screen). */
    resume() {
      paused = false;
      if (!job) return;
      const mine = ++token;
      api
        .job(job.id)
        .then((next) => mine === token && (update(next), schedule()))
        .catch((err) => mine === token && status.set(err.message, "error"));
    },
    current: () => job,
  };
}
