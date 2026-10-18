// Audio helpers: object URLs that are always revoked, previews, streamed-WAV header repair.

import * as api from "./api.js";

const UNKNOWN = 0xffffffff;

/**
 * The server streams WAV with "unknown length" size fields. Once the whole body has arrived,
 * write the real sizes so players show a duration and downloads open everywhere.
 * @param {Blob} blob
 * @returns {Promise<Blob>}
 */
export async function finalizeWav(blob) {
  const buf = await blob.arrayBuffer();
  const view = new DataView(buf);
  const isWav =
    buf.byteLength >= 44 &&
    view.getUint32(0, false) === 0x52494646 && // "RIFF"
    view.getUint32(36, false) === 0x64617461; // "data"
  if (isWav && view.getUint32(40, true) === UNKNOWN) {
    view.setUint32(4, buf.byteLength - 8, true);
    view.setUint32(40, buf.byteLength - 44, true);
  }
  return new Blob([buf], { type: "audio/wav" });
}

/** Holds one object URL at a time and revokes the previous one when replaced. */
export class ObjectUrlSlot {
  constructor() {
    this.url = "";
  }
  /** @param {Blob|null} blob */
  set(blob) {
    if (this.url) URL.revokeObjectURL(this.url);
    this.url = blob ? URL.createObjectURL(blob) : "";
    return this.url;
  }
}

const previewAudio = new Audio();
const previewSlot = new ObjectUrlSlot();
let previewToken = 0;
let previewButton = null;

function resetButton() {
  if (previewButton) {
    previewButton.setAttribute("aria-pressed", "false");
    previewButton.classList.remove("playing");
    previewButton = null;
  }
}
previewAudio.addEventListener("ended", resetButton);
previewAudio.addEventListener("pause", resetButton);

/**
 * Play (or stop, when already playing from the same button) a voice preview.
 * @param {string} voiceId
 * @param {string} language
 * @param {HTMLButtonElement} [button] toggles aria-pressed while playing
 */
export async function playPreview(voiceId, language, button) {
  if (button && previewButton === button && !previewAudio.paused) {
    previewAudio.pause();
    return;
  }
  previewAudio.pause();
  const token = ++previewToken;
  if (button) button.classList.add("loading");
  try {
    const blob = await api.preview(voiceId, language);
    if (token !== previewToken) return;
    previewAudio.src = previewSlot.set(blob);
    await previewAudio.play();
    if (button) {
      previewButton = button;
      button.setAttribute("aria-pressed", "true");
      button.classList.add("playing");
    }
  } finally {
    if (button) button.classList.remove("loading");
  }
}

/** Stop any preview (e.g. when leaving a screen). */
export function stopPreview() {
  previewToken++;
  previewAudio.pause();
}
