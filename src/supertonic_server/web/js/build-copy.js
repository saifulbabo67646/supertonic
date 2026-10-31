// Shared wording for voice building: method names, stages, job states and build metadata.

import { h } from "./dom.js";
import { BUILDER_GUIDE_URL } from "./errors.js";

/** Radio labels for the build methods, in display order. */
export const METHODS = [
  ["accurate", "Best match — about 1½ hours"],
  ["fast", "Quick draft — about 15 minutes"],
];

/** One line under each method choice. */
export const METHOD_HELP = {
  accurate: "Takes longer, but sounds closest to the speaker. Best for a voice you will keep.",
  fast: "A fast first try. Good for checking that your recording works.",
};

/** Short method names for cards and lists. */
export const METHOD_NAMES = { accurate: "Best match", fast: "Quick draft" };

export const STAGE_LABELS = {
  loading: "Getting ready",
  preset: "Finding the closest built-in voice",
  timbre: "Matching the sound of the voice",
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

/** Where builds run, for the progress panel ("local" or "remote" from the server). */
export const BUILDER_PLACES = {
  local: "building on this computer",
  remote: "building on the connected computer",
};

/**
 * The card shown instead of the New voice form when this server cannot build voices:
 * why (an NVIDIA graphics card is needed) and the two ways to get one.
 * @param {string} headingId id for the card's heading
 */
export function noBuilderCard(headingId) {
  const guide = (anchor, text) =>
    h("a", { href: `${BUILDER_GUIDE_URL}#${anchor}`, target: "_blank", rel: "noopener", text });
  return h(
    "section",
    { class: "no-builder panel", "aria-labelledby": headingId },
    h("h2", { id: headingId, text: "Making new voices needs an NVIDIA graphics card" }),
    h("p", {
      text:
        "Building a voice from a recording takes a lot of computing power, so Supertonic does " +
        "it on a computer with an NVIDIA graphics card. This server is not set up for that. " +
        "Everything else works as normal: speaking, the built-in voices and connecting apps.",
    }),
    h("p", { text: "To make your own voices, choose one of these:" }),
    h(
      "ol",
      { class: "options" },
      h(
        "li",
        {},
        h("strong", { text: "Use a computer that has an NVIDIA graphics card. " }),
        "Install Supertonic there and build voices on it. ",
        guide("setting-up-a-builder", "How to set it up"),
      ),
      h(
        "li",
        {},
        h("strong", { text: "Connect this server to one. " }),
        "Keep using this computer and send voice building to a computer with the card. ",
        guide("forwarding-builds", "How to connect them"),
      ),
    ),
    h("p", {
      class: "hint",
      text: "Already have a voice file (.json)? Add it on the Voices page under “Add a voice from a file”.",
    }),
  );
}

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
  if (typeof build.similarity === "number") {
    rows.push(["Likeness score", `${build.similarity.toFixed(3)} (1 is a perfect match)`]);
  }
  if (typeof build.stopped_early === "boolean") {
    rows.push(["Finished early", build.stopped_early ? "Yes" : "No"]);
  }
  if (typeof build.seconds === "number") rows.push(["Build time", duration(build.seconds)]);
  return h(
    "dl",
    { class: "facts" },
    rows.map(([k, v]) => h("div", {}, h("dt", { text: k }), h("dd", { text: v }))),
  );
}
