// Cached server catalog (languages, voices, health) shared by the screens.

import * as api from "./api.js";

let languagesPromise = null;
let voicesPromise = null;
let healthPromise = null;
const listeners = new Set();

/** Languages are static for the life of the server, so fetch once. */
export function getLanguages() {
  languagesPromise ??= api.languages().catch((err) => {
    languagesPromise = null;
    throw err;
  });
  return languagesPromise;
}

/** Voices, cached until `refreshVoices()`. */
export function getVoices() {
  voicesPromise ??= api.voices().catch((err) => {
    voicesPromise = null;
    throw err;
  });
  return voicesPromise;
}

/** Drop the voice cache, refetch and notify subscribers. */
export async function refreshVoices() {
  voicesPromise = null;
  const list = await getVoices();
  for (const fn of listeners) fn(list);
  return list;
}

/** Call `fn(voices)` whenever the voice list is refreshed. */
export function onVoicesChanged(fn) {
  listeners.add(fn);
}

/** GET /v1/health, cached. */
export function getHealth() {
  healthPromise ??= api.health().catch((err) => {
    healthPromise = null;
    throw err;
  });
  return healthPromise;
}

/** Label shown for a voice in pickers, e.g. "Mia · F1". */
export function voiceLabel(voice) {
  return voice.name === voice.id ? voice.id : `${voice.name} · ${voice.id}`;
}
