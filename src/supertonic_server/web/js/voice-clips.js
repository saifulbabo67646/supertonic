// Reference clips for a new voice: drag-and-drop or pick 1–3 audio files, plus an optional take.

import { h, replace } from "./dom.js";
import { buildRecorder, MAX_SECONDS, MIN_SECONDS } from "./voice-record.js";

export const MAX_FILES = 3;
export const MAX_BYTES = 25 * 1024 * 1024;
const ACCEPT = "audio/*,.wav,.mp3,.m4a,.aac,.flac,.ogg,.opus,.webm";

const mb = (bytes) => `${(bytes / (1024 * 1024)).toFixed(1)} MB`;

/** Duration of an audio file in seconds, or null when the browser cannot tell. */
function probeSeconds(file) {
  return new Promise((resolve) => {
    const url = URL.createObjectURL(file);
    const audio = new Audio();
    const done = (value) => {
      URL.revokeObjectURL(url);
      audio.removeAttribute("src");
      resolve(value);
    };
    audio.preload = "metadata";
    audio.addEventListener("loadedmetadata", () =>
      done(Number.isFinite(audio.duration) ? audio.duration : null),
    );
    audio.addEventListener("error", () => done(null));
    audio.src = url;
  });
}

/**
 * Build the clip picker.
 * @param {(text: string) => void} onError shows an error about the chosen files
 * @returns {{el: HTMLElement, files: () => File[], check: () => string, reset: () => void,
 *   cancel: () => void}}
 */
export function buildClips(onError) {
  const uploads = [];
  const input = h("input", {
    type: "file",
    id: "clip-input",
    accept: ACCEPT,
    multiple: true,
    "aria-describedby": "clip-hint",
  });
  const list = h("ul", { class: "clips", "aria-label": "Chosen recordings" });
  const summary = h("p", { class: "meta", "aria-live": "polite" });
  const zone = h(
    "div",
    { class: "dropzone" },
    h("label", { for: "clip-input", text: "Reference recordings" }),
    h("p", {
      class: "hint",
      id: "clip-hint",
      text: `Drop up to ${MAX_FILES} audio files here, or choose them. One speaker only, little background noise. ${MIN_SECONDS} to ${MAX_SECONDS} seconds of speech in total, up to 25 MB.`,
    }),
    input,
  );
  const recorder = buildRecorder(render);

  function all() {
    const take = recorder.take();
    return take ? [...uploads, take] : [...uploads];
  }

  function add(files) {
    const room = MAX_FILES - all().length;
    const chosen = [...files];
    if (chosen.length > room) {
      onError(`Use at most ${MAX_FILES} recordings in total (including one recorded here).`);
    }
    for (const file of chosen.slice(0, Math.max(0, room))) {
      uploads.push(file);
      probeSeconds(file).then((secs) => {
        file.seconds = secs;
        render();
      });
    }
    input.value = "";
    render();
  }

  function render() {
    replace(
      list,
      uploads.map((file, i) => {
        const remove = h("button", { type: "button", class: "btn ghost small", text: "Remove" });
        remove.setAttribute("aria-label", `Remove ${file.name}`);
        remove.addEventListener("click", () => {
          uploads.splice(i, 1);
          render();
          input.focus();
        });
        const secs = typeof file.seconds === "number" ? `, ${file.seconds.toFixed(1)} s` : "";
        return h(
          "li",
          {},
          h("span", { class: "clip-name", text: file.name }),
          h("span", { class: "meta", text: `${mb(file.size)}${secs}` }),
          remove,
        );
      }),
    );
    const files = all();
    input.disabled = files.length >= MAX_FILES;
    if (!files.length) {
      summary.textContent = "";
      return;
    }
    const bytes = files.reduce((n, f) => n + f.size, 0);
    const known = files.every((f) => typeof f.seconds === "number");
    const secs = files.reduce((n, f) => n + (f.seconds || 0), 0);
    let text = `${files.length} of ${MAX_FILES} recordings, ${mb(bytes)}`;
    if (known) text += `, about ${Math.round(secs)} s`;
    if (bytes > MAX_BYTES) text += ". That is over the 25 MB limit.";
    else if (known && secs < MIN_SECONDS) text += `. That is under ${MIN_SECONDS} seconds.`;
    else if (known && secs > MAX_SECONDS) {
      text += `. More than ${MAX_SECONDS} seconds of speech (after silence is trimmed) is rejected.`;
    }
    summary.textContent = text;
  }

  zone.addEventListener("dragover", (e) => {
    e.preventDefault();
    zone.classList.add("over");
  });
  zone.addEventListener("dragleave", () => zone.classList.remove("over"));
  zone.addEventListener("drop", (e) => {
    e.preventDefault();
    zone.classList.remove("over");
    if (e.dataTransfer?.files?.length) add(e.dataTransfer.files);
  });
  input.addEventListener("change", () => add(input.files));

  return {
    el: h("div", { class: "clip-picker" }, zone, list, summary, recorder.el),
    files: all,
    /** A blocking problem with the chosen files, or "". */
    check() {
      const files = all();
      if (!files.length) return "Add a recording: upload a file or record one.";
      if (files.length > MAX_FILES) return `Use at most ${MAX_FILES} recordings.`;
      if (files.reduce((n, f) => n + f.size, 0) > MAX_BYTES) {
        return "The recordings are over 25 MB in total. Use shorter or compressed files.";
      }
      return "";
    },
    reset() {
      uploads.length = 0;
      recorder.reset();
      render();
    },
    cancel: recorder.cancel,
  };
}
