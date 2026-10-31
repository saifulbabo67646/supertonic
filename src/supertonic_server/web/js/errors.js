// Plain-language error messages: what went wrong and what to do next, never a raw code first.
// Pure module (no DOM), so it can be unit-tested outside the browser.

/** The beginner guide and the voice building guide on GitHub. */
export const GUIDE_URL =
  "https://github.com/saifulbabo67646/supertonic/blob/main/docs/getting-started.md";
export const BUILDER_GUIDE_URL =
  "https://github.com/saifulbabo67646/supertonic/blob/main/docs/builder.md";
export const TROUBLESHOOTING_URL =
  "https://github.com/saifulbabo67646/supertonic/blob/main/docs/troubleshooting.md";

const UNREACHABLE =
  "Supertonic is not responding. Check that its window is still open (or start it again), " +
  "then try once more.";

/** A friendlier sentence for a problem with a reference recording, from the server's reason. */
function recordingProblem(message) {
  const speech = /has ([\d.]+) s of speech/.exec(message);
  if (/need at least/.test(message)) {
    const got = speech ? ` (only ${speech[1]} seconds were found)` : "";
    return (
      `The recording has too little speech${got}. Record at least a few seconds of ` +
      "talking; about 30 seconds works best."
    );
  }
  if (/at most [\d.]+ s/.test(message)) {
    return (
      "The recording has more than 60 seconds of speech. Use a shorter recording, or " +
      "remove one of the files."
    );
  }
  if (/silence/.test(message)) {
    return (
      "The recording is mostly silence. Speak a little closer to the microphone and " +
      "record again."
    );
  }
  if (/not decodable|timed out/.test(message)) {
    return "One of the files could not be read as audio. Try a WAV, MP3 or M4A file instead.";
  }
  if (/longer than/.test(message)) {
    return "One of the files is very long. Cut it down to the part with the speaker, under a minute.";
  }
  if (/exceeds/.test(message)) {
    return "The files are too big together (25 MB at most). Use shorter recordings.";
  }
  if (/provide 1 to/.test(message)) return "Add one to three recordings, then try again.";
  return `There is a problem with the recording: ${message}`;
}

/** Messages by API error code. */
const BUSY = "Supertonic is busy right now. Wait a moment and try again.";

const BY_CODE = {
  server_busy: () => BUSY,
  not_ready: () => "Supertonic is still starting up. Wait a few seconds and try again.",
  voice_not_found: () => "That voice no longer exists. Pick another voice.",
  ambiguous_voice: () =>
    "More than one voice has that name. Rename one of them on the Voices page.",
  voice_name_taken: () => "That name belongs to a built-in voice. Choose a different name.",
  voice_read_only: () => "Built-in voices cannot be changed or deleted.",
  invalid_reference_audio: (m) => recordingProblem(m),
  invalid_style: () =>
    "That file is not a Supertonic voice file. Choose a .json file saved with " +
    "“Download voice file”.",
  empty_input: () => "Write something to speak first.",
  consent_required: () =>
    "Say where the recording is from and confirm you have the speaker's permission.",
  builder_unavailable: () =>
    "The voice builder cannot be reached right now. Make sure the computer that builds " +
    "voices is switched on and running Supertonic, then try again.",
  builder_busy: () =>
    "The voice builder is busy with other voices. Try again in a little while.",
  job_not_found: () => "That build no longer exists. It may have been removed.",
  job_not_running: () => "That build has not started yet, so there is nothing to keep.",
  payload_too_large: () => "That is too much to send at once. Use a smaller file or shorter text.",
  interrupted: () =>
    "The build stopped because Supertonic was restarted. Start the build again.",
};

/**
 * A sentence a non-technical person can act on.
 * @param {{message?: string, status?: number, code?: string}} err an ApiError (or any Error)
 * @returns {string}
 */
export function friendlyError(err) {
  const message = String(err?.message || "");
  const code = err?.code || "";
  if (Object.hasOwn(BY_CODE, code)) return BY_CODE[code](message);
  const status = err?.status ?? 0;
  if (status === 0 && /Could not reach the server/.test(message)) return UNREACHABLE;
  if (status === 401) {
    return "This server needs an access key. Enter it on the Connect page, then try again.";
  }
  if (status === 429) return BUSY;
  if (status >= 500) {
    return (
      "Something went wrong inside Supertonic. Try again; if it keeps happening, restart " +
      `Supertonic. (Details: ${message || `error ${status}`})`
    );
  }
  return message || "Something went wrong. Try again.";
}

/** Plain text for a failed build job's `error` ({code, message}). */
export function friendlyJobError(error) {
  if (!error) return "The build did not finish. Try building again.";
  if (Object.hasOwn(BY_CODE, error.code)) return BY_CODE[error.code](error.message || "");
  const detail = error.message ? ` (Details: ${error.message})` : "";
  return `The build did not finish. Try building again.${detail}`;
}
