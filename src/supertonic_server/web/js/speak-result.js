// "Latest take" panel on Speak: the player and a download button for the chosen file type.

import { ObjectUrlSlot } from "./audio.js";
import { fileStamp, h, replace } from "./dom.js";

/** File types offered on Speak, in display order, with plain-language help. */
export const FORMATS = [
  { value: "mp3", label: "MP3", hint: "smaller file, best for sharing" },
  { value: "wav", label: "WAV", hint: "full quality, best for editing" },
];

/** A file name like "Mia-en-20261031-153012.mp3" (characters unsafe in file names replaced). */
export function takeFileName(voiceName, language, date, format) {
  const safe = String(voiceName)
    .replace(/[^\p{L}\p{N}_-]+/gu, "-")
    .replace(/^-+|-+$/g, "");
  return `${safe || "speech"}-${language}-${fileStamp(date)}.${format}`;
}

/**
 * Build the panel. `show(take)` displays a finished take:
 * {blob, format, voiceName, languageName, language, speed, date}.
 */
export function createResult() {
  const slot = new ObjectUrlSlot();
  const player = h("audio", { controls: true, preload: "auto" });
  player.setAttribute("aria-label", "Latest take");
  const meta = h("p", { class: "meta" });
  const download = h("a", { class: "btn primary", href: "#", text: "Download" });
  const hint = h("p", { class: "hint" });
  const el = h(
    "section",
    { class: "result panel", "aria-labelledby": "result-title", hidden: true },
    h("h2", { id: "result-title", text: "Latest take" }),
    meta,
    h("div", { class: "player-row" }, player, download),
    hint,
  );
  return {
    el,
    /** Show a finished take and start playing it. */
    show(take) {
      const url = slot.set(take.blob);
      player.src = url;
      download.href = url;
      download.download = takeFileName(take.voiceName, take.language, take.date, take.format);
      const type = FORMATS.find((f) => f.value === take.format) || FORMATS[0];
      download.textContent = `Download ${type.label}`;
      const other = FORMATS.find((f) => f !== type);
      hint.textContent =
        `Saved as ${type.label}: ${type.hint}. For ${other.label} (${other.hint}), ` +
        `change File type and press Generate again.`;
      replace(meta, `${take.voiceName}, ${take.languageName}, speed ${take.speed.toFixed(2)}`);
      el.hidden = false;
      player.play().catch(() => {});
    },
  };
}
