// Fetch wrapper for the Supertonic API: same origin, Bearer key, 401 → key dialog, typed errors.

import { askForKey } from "./keydialog.js";
import { getApiKey, setApiKey } from "./store.js";

export const BASE_URL = window.location.origin;

/** An error returned by the API ({"error": {message, type, code, param}}) or the network. */
export class ApiError extends Error {
  constructor(message, { status = 0, type = "", code = "", param = null } = {}) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.type = type;
    this.code = code;
    this.param = param;
  }
}

async function toError(res) {
  let body = null;
  try {
    body = await res.json();
  } catch {
    // Not JSON; fall through to a generic message.
  }
  const err = body && typeof body === "object" ? body.error : null;
  if (err && typeof err.message === "string") {
    return new ApiError(err.message, { status: res.status, ...err });
  }
  return new ApiError(`Request failed with HTTP ${res.status}`, { status: res.status });
}

/**
 * Perform a request and return the Response when it is OK; throw ApiError otherwise.
 * On 401 the key dialog opens; a new key is saved and the request retried.
 * @param {string} path e.g. "/v1/voices"
 * @param {RequestInit & {json?: any}} [options]
 */
export async function request(path, options = {}) {
  const { json, headers = {}, ...rest } = options;
  const init = { ...rest, headers: { ...headers } };
  if (json !== undefined) {
    init.body = JSON.stringify(json);
    init.headers["Content-Type"] = "application/json";
  }
  let rejected = false;
  for (;;) {
    const key = getApiKey();
    if (key) init.headers.Authorization = `Bearer ${key}`;
    else delete init.headers.Authorization;
    let res;
    try {
      res = await fetch(BASE_URL + path, init);
    } catch (exc) {
      throw new ApiError(`Could not reach the server (${exc.message || "network error"})`);
    }
    if (res.ok) return res;
    if (res.status !== 401) throw await toError(res);
    const message = key || rejected ? "That key was not accepted. Check it and try again." : "";
    const next = await askForKey(message);
    if (!next) throw await toError(res);
    setApiKey(next);
    rejected = true;
  }
}

/** Request and parse JSON. */
export async function getJson(path, options) {
  const res = await request(path, options);
  return res.status === 204 ? null : res.json();
}

/** GET /v1/health (never requires a key). */
export const health = () => getJson("/v1/health");
/** GET /v1/languages → array. */
export const languages = async () => (await getJson("/v1/languages")).data;
/** GET /v1/voices → array. */
export const voices = async () => (await getJson("/v1/voices")).data;

/** POST /v1/audio/speech → Blob. */
export async function speech(params) {
  const res = await request("/v1/audio/speech", {
    method: "POST",
    json: { model: "supertonic-3", ...params },
  });
  return res.blob();
}

/** GET a voice preview WAV → Blob. */
export async function preview(voiceId, language) {
  const q = new URLSearchParams({ language });
  const res = await request(`/v1/voices/${encodeURIComponent(voiceId)}/preview?${q}`);
  return res.blob();
}

/** GET /v1/voices/{id}/style → Blob (JSON). */
export async function exportStyle(voiceId) {
  const res = await request(`/v1/voices/${encodeURIComponent(voiceId)}/style`);
  return res.blob();
}

/** PATCH a custom voice. */
export const updateVoice = (voiceId, patch) =>
  getJson(`/v1/voices/${encodeURIComponent(voiceId)}`, { method: "PATCH", json: patch });

/** DELETE a custom voice. */
export const deleteVoice = (voiceId) =>
  getJson(`/v1/voices/${encodeURIComponent(voiceId)}`, { method: "DELETE" });

/** POST /v1/voices/import with multipart form data (file, name, description, tags, source_note). */
export const importVoice = (formData) =>
  getJson("/v1/voices/import", { method: "POST", body: formData });
