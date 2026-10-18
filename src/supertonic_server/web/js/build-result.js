// Finished-build panel: build facts, a language picker, "Try it" on Speak and the voice card link.

import { buildFacts } from "./build-copy.js";
import { getLanguages, getVoices, refreshVoices } from "./catalog.js";
import { h } from "./dom.js";

/**
 * Load what the panel needs (refreshing the voice list so the new voice shows everywhere).
 * Never throws: a failed request leaves `languages` empty or `voice` null.
 * @returns {Promise<{languages: object[], voice: object|null, error: string}>}
 */
export async function loadResult(voiceId) {
  try {
    const [languages] = await Promise.all([getLanguages(), refreshVoices()]);
    const voice = (await getVoices()).find((v) => v.id === voiceId) || null;
    return { languages, voice, error: "" };
  } catch (err) {
    return { languages: [], voice: null, error: err.message };
  }
}

/**
 * The panel's nodes for a succeeded job; `tryIt` is returned for focusing.
 * Without the language list, Try it keeps Speak's own language choice.
 */
export function resultNodes(job, { languages, voice }) {
  const vid = encodeURIComponent(job.voice_id);
  const tryIt = h("a", { class: "btn primary", text: "Try it" });
  let lang = null;
  if (languages.length) {
    lang = h(
      "select",
      { class: "compact", "aria-label": "Language to try" },
      languages.map((l) => h("option", { value: l.code, text: `${l.name} (${l.code})` })),
    );
    lang.value = languages.some((l) => l.code === "en") ? "en" : languages[0].code;
  }
  const setHref = () => {
    const q = lang ? `&language=${encodeURIComponent(lang.value)}` : "";
    tryIt.href = `#/speak?voice=${vid}${q}`;
  };
  lang?.addEventListener("change", setHref);
  setHref();
  const nodes = [
    h("p", { text: `${job.request.name} is ready as ${job.voice_id}.` }),
    voice?.build ? buildFacts(voice.build) : null,
    h(
      "div",
      { class: "row" },
      lang,
      tryIt,
      h("a", { class: "btn", href: `#/voices?voice=${vid}`, text: "Open voice card" }),
    ),
  ];
  return { nodes, tryIt };
}
