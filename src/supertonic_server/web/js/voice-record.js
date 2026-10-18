// In-browser recording for a new voice: MediaRecorder with elapsed time, level meter and re-record.

import { ObjectUrlSlot } from "./audio.js";
import { h, replace, statusLine } from "./dom.js";

export const MIN_SECONDS = 3;
export const MAX_SECONDS = 60;

// Preferred containers, best first. Chrome and Firefox record webm/opus, Safari records mp4/aac.
const TYPES = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg;codecs=opus"];

/** Why recording is impossible here, or "" when it should work. */
function unsupportedReason() {
  if (!window.isSecureContext) {
    return "Recording needs a secure page (https or localhost). Upload a file instead.";
  }
  if (!navigator.mediaDevices?.getUserMedia || typeof window.MediaRecorder !== "function") {
    return "This browser cannot record audio. Upload a file instead.";
  }
  return "";
}

function pickType() {
  if (typeof MediaRecorder.isTypeSupported !== "function") return "";
  return TYPES.find((t) => MediaRecorder.isTypeSupported(t)) || "";
}

/** File extension for a recorded MIME type. */
export function extensionFor(mime) {
  if (mime.includes("mp4") || mime.includes("aac")) return "m4a";
  if (mime.includes("ogg")) return "ogg";
  return "webm";
}

function micError(err) {
  if (err && (err.name === "NotAllowedError" || err.name === "SecurityError")) {
    return "Microphone access was blocked. Allow it in the browser's site settings, or upload a file instead.";
  }
  if (err && err.name === "NotFoundError") {
    return "No microphone was found. Connect one, or upload a file instead.";
  }
  return `Could not start recording: ${err?.message || "unknown error"}`;
}

const clock = (s) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;

/**
 * Build the recorder.
 * @param {() => void} onChange called whenever the take is added, replaced or removed
 * @returns {{el: HTMLElement, take: () => File|null, cancel: () => void, reset: () => void}}
 */
export function buildRecorder(onChange) {
  const slot = new ObjectUrlSlot();
  const status = statusLine();
  const body = h("div", { class: "recorder-body" });
  const el = h(
    "div",
    { class: "recorder", role: "group", "aria-labelledby": "recorder-title" },
    h("h3", { id: "recorder-title", text: "Or record in the browser" }),
    h("p", {
      class: "hint",
      text: `Read naturally in a quiet room for ${MIN_SECONDS} to ${MAX_SECONDS} seconds; 10 to 30 seconds works well. Recording stops by itself at ${MAX_SECONDS} seconds.`,
    }),
    body,
    status,
  );
  let take = null;
  let session = null;
  /** Bumped by cancel(); a microphone request from an older attempt is thrown away. */
  let attempt = 0;
  let asking = false;

  function idle() {
    // When the focused control (e.g. Stop recording) is replaced, focus the new Record button.
    const hadFocus = body.contains(document.activeElement);
    const reason = unsupportedReason();
    const start = h("button", {
      type: "button",
      class: "btn",
      disabled: Boolean(reason),
      text: take ? "Re-record" : "Record",
    });
    start.addEventListener("click", begin);
    if (reason) status.set(reason, "info");
    if (!take) {
      replace(body, h("div", { class: "row" }, start));
      if (hadFocus) start.focus();
      return;
    }
    const player = h("audio", { controls: true, preload: "metadata", src: slot.url });
    player.setAttribute("aria-label", "Your recording");
    const remove = h("button", { type: "button", class: "btn ghost small", text: "Remove" });
    remove.addEventListener("click", () => {
      take = null;
      slot.set(null);
      status.clear();
      idle();
      onChange();
    });
    replace(
      body,
      h("p", { class: "meta", text: `${take.name}, ${clock(take.seconds)}` }),
      h("div", { class: "player-row" }, player),
      h("div", { class: "row" }, start, remove),
    );
    if (hadFocus) start.focus();
  }

  async function begin(event) {
    if (asking || session) return;
    asking = true;
    event.currentTarget.disabled = true;
    const mine = ++attempt;
    status.set("Waiting for microphone permission…", "busy");
    let stream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch (err) {
      if (mine === attempt) {
        asking = false;
        status.set(micError(err), "error");
        idle();
      }
      return;
    }
    if (mine !== attempt) {
      // The screen was left (or the recorder reset) while the permission prompt was open.
      stream.getTracks().forEach((t) => t.stop());
      return;
    }
    asking = false;
    let recorder;
    try {
      const type = pickType();
      recorder = new MediaRecorder(stream, type ? { mimeType: type } : undefined);
    } catch (err) {
      stream.getTracks().forEach((t) => t.stop());
      status.set(`Could not start recording: ${err.message}`, "error");
      idle();
      return;
    }
    const chunks = [];
    const s = {
      stream,
      recorder,
      chunks,
      started: performance.now(),
      raf: 0,
      ctx: null,
      keep: true,
    };
    session = s;
    recorder.addEventListener("dataavailable", (e) => e.data.size && chunks.push(e.data));
    recorder.addEventListener("stop", () => finish(s));
    recorder.start(250);
    recording(s);
  }

  function recording(s) {
    const time = h("span", { class: "rec-time", role: "timer", text: "0:00" });
    const level = h("span", { class: "level-fill" });
    const stop = h("button", { type: "button", class: "btn primary", text: "Stop recording" });
    stop.addEventListener("click", () => s.recorder.state !== "inactive" && s.recorder.stop());
    replace(
      body,
      h(
        "div",
        { class: "rec-live" },
        h("span", { class: "rec-dot", "aria-hidden": "true" }),
        time,
        h("span", { class: "level", "aria-hidden": "true" }, level),
      ),
      h("div", { class: "row" }, stop),
    );
    status.set("Recording…", "busy");
    stop.focus();
    let data = null;
    let analyser = null;
    try {
      s.ctx = new AudioContext();
      s.ctx.resume().catch(() => {}); // Safari starts contexts suspended
      analyser = s.ctx.createAnalyser();
      analyser.fftSize = 1024;
      s.ctx.createMediaStreamSource(s.stream).connect(analyser);
      data = new Float32Array(analyser.fftSize);
    } catch {
      // No Web Audio: record without the level meter.
    }
    const tick = () => {
      const secs = (performance.now() - s.started) / 1000;
      time.textContent = clock(secs);
      if (analyser) {
        analyser.getFloatTimeDomainData(data);
        const rms = Math.sqrt(data.reduce((sum, v) => sum + v * v, 0) / data.length);
        const db = 20 * Math.log10(rms || 1e-6);
        level.style.width = `${Math.max(0, Math.min(1, (db + 60) / 60)) * 100}%`;
      }
      if (secs >= MAX_SECONDS && s.recorder.state === "recording") s.recorder.stop();
      else s.raf = requestAnimationFrame(tick);
    };
    s.raf = requestAnimationFrame(tick);
  }

  function release(s) {
    cancelAnimationFrame(s.raf);
    s.stream.getTracks().forEach((t) => t.stop());
    if (s.ctx) s.ctx.close().catch(() => {});
  }

  function finish(s) {
    release(s);
    if (session === s) session = null;
    if (!s.keep) return;
    const seconds = Math.min(MAX_SECONDS, (performance.now() - s.started) / 1000);
    const mime = s.recorder.mimeType || s.chunks[0]?.type || "audio/webm";
    const blob = new Blob(s.chunks, { type: mime });
    if (!blob.size) {
      status.set("Nothing was recorded. Check the microphone and try again.", "error");
      idle();
      return;
    }
    take = new File([blob], `recording.${extensionFor(mime)}`, { type: mime });
    take.seconds = seconds;
    slot.set(take);
    if (seconds < MIN_SECONDS) {
      status.set(`That take is under ${MIN_SECONDS} seconds. Record a longer one.`, "error");
    } else {
      status.set(`Recorded ${clock(seconds)}. It will be sent with the form.`, "ok");
    }
    idle();
    onChange();
  }

  /** Stop any recording in progress and throw it away (e.g. when leaving the screen). */
  function cancel() {
    attempt++;
    if (asking) {
      asking = false;
      status.clear();
      idle();
    }
    const s = session;
    if (!s) return;
    s.keep = false;
    session = null;
    if (s.recorder.state !== "inactive") s.recorder.stop();
    else release(s);
    status.clear();
    idle();
  }

  /** Cancel and forget the take (after a successful submit). */
  function reset() {
    cancel();
    take = null;
    slot.set(null);
    status.clear();
    idle();
  }

  idle();
  return { el, take: () => take, cancel, reset };
}
