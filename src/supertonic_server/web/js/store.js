// Browser storage that degrades gracefully when localStorage is blocked or unavailable.

const KEY_STORAGE = "supertonic.apiKey";
const HISTORY_STORAGE = "supertonic.history.v1";
const HISTORY_MAX = 20;

let memoryKey = "";

function read(name) {
  try {
    return window.localStorage.getItem(name);
  } catch {
    return null;
  }
}

function write(name, value) {
  try {
    if (value === null) window.localStorage.removeItem(name);
    else window.localStorage.setItem(name, value);
    return true;
  } catch {
    return false;
  }
}

/** The saved API key, or "" when none. Falls back to memory if storage is unavailable. */
export function getApiKey() {
  return read(KEY_STORAGE) || memoryKey;
}

/** Save (or with "" forget) the API key. */
export function setApiKey(key) {
  memoryKey = key;
  write(KEY_STORAGE, key ? key : null);
}

/**
 * Recent generations, newest first. Each: {text, voice, language, speed, steps, timestamp}.
 * @returns {Array<object>}
 */
export function getHistory() {
  try {
    const parsed = JSON.parse(read(HISTORY_STORAGE) || "[]");
    return Array.isArray(parsed)
      ? parsed.filter((e) => e && typeof e.text === "string" && Number.isFinite(e.timestamp))
      : [];
  } catch {
    return [];
  }
}

/** Add an entry to the front of the history (capped at 20) and return the new list. */
export function addHistory(entry) {
  const list = [entry, ...getHistory()].slice(0, HISTORY_MAX);
  write(HISTORY_STORAGE, JSON.stringify(list));
  return list;
}

/** Remove all history. */
export function clearHistory() {
  write(HISTORY_STORAGE, null);
}

const WELCOME_STORAGE = "supertonic.welcomeDismissed";

/** Whether the first-run welcome was dismissed in this browser. */
export function welcomeDismissed() {
  return read(WELCOME_STORAGE) === "1";
}

/** Remember that the welcome was dismissed (or with `false`, show it again). */
export function setWelcomeDismissed(dismissed = true) {
  write(WELCOME_STORAGE, dismissed ? "1" : null);
}
