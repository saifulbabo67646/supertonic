// Shared wording for voice building: method names, stages, job states and build metadata.

import { h } from "./dom.js";

/** Radio labels for the build methods, in display order. */
export const METHODS = [
  ["accurate", "Best match — about 1½ hours"],
  ["fast", "Quick draft — about 15 minutes"],
];

/** Short method names for cards and lists. */
export const METHOD_NAMES = { accurate: "Best match", fast: "Quick draft" };

export const STAGE_LABELS = {
  loading: "Loading models",
  preset: "Finding the closest preset voice",
  timbre: "Matching the timbre",
  duration: "Matching the speaking rhythm",
  saving: "Saving the voice",
};

/** Stage text after Finish now, for the stages that still run after the timbre stops. */
export const FINISHING_LABELS = {
  duration: "Finishing: matching the speaking pace…",
  saving: "Finishing: saving the voice…",
};

export const STATE_LABELS = {
  queued: "Waiting",
  running: "Building",
  succeeded: "Ready",
  failed: "Failed",
  cancelled: "Cancelled",
};

export const ACTIVE_STATES = new Set(["queued", "running"]);

export const NO_BUILDER_TEXT =
  "Voice building is not enabled on this server. Install the builder extra on a machine with an " +
  "NVIDIA GPU (uv sync --extra builder), or set SUPERTONIC_BUILDER_URL to forward builds to one, " +
  "then restart the server.";

export const LICENCE_TEXT =
  "Voices built here are derived from the Supertonic 3 model, so the use restrictions of its " +
  "OpenRAIL-M licence apply to them and to everything they say. Do not use a voice to " +
  "impersonate, deceive or harm anyone.";

export const LICENCE_URL = "https://huggingface.co/Supertone/supertonic-3";

/** Minutes and seconds, e.g. "1 h 05 min", "12 min 30 s", "40 s". */
export function duration(seconds) {
  const s = Math.max(0, Math.round(seconds));
  if (s >= 3600) {
    return `${Math.floor(s / 3600)} h ${String(Math.floor((s % 3600) / 60)).padStart(2, "0")} min`;
  }
  if (s >= 60) return `${Math.floor(s / 60)} min ${String(s % 60).padStart(2, "0")} s`;
  return `${s} s`;
}

/** A definition list of a built voice's metadata (method, similarity, stopped early, time). */
export function buildFacts(build) {
  const rows = [["Built with", METHOD_NAMES[build.method] || build.method || "unknown"]];
  if (typeof build.similarity === "number") rows.push(["Similarity", build.similarity.toFixed(3)]);
  if (typeof build.stopped_early === "boolean") {
    rows.push(["Stopped early", build.stopped_early ? "Yes" : "No"]);
  }
  if (typeof build.seconds === "number") rows.push(["Build time", duration(build.seconds)]);
  return h(
    "dl",
    { class: "facts" },
    rows.map(([k, v]) => h("div", {}, h("dt", { text: k }), h("dd", { text: v }))),
  );
}
