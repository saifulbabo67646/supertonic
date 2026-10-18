// Small DOM helpers. All text goes through textContent; nothing user-controlled is parsed as HTML.

/**
 * Create an element.
 * @param {string} tag
 * @param {Record<string, any>} [attrs] attributes; `class`, `text`, `on<Event>` and booleans handled
 * @param {...(Node|string|null|undefined|false)} children
 */
export function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value === undefined || value === null || value === false) continue;
    if (key === "class") el.className = value;
    else if (key === "text") el.textContent = value;
    else if (key.startsWith("on") && typeof value === "function") {
      el.addEventListener(key.slice(2).toLowerCase(), value);
    } else if (value === true) el.setAttribute(key, "");
    else el.setAttribute(key, String(value));
  }
  append(el, children);
  return el;
}

/** Append children (strings become text nodes). */
export function append(parent, children) {
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) continue;
    parent.append(typeof child === "string" ? document.createTextNode(child) : child);
  }
  return parent;
}

/** Replace all children of `parent`. */
export function replace(parent, ...children) {
  parent.replaceChildren();
  return append(parent, children);
}

/** A labelled form field: returns the wrapper; the control is `wrapper.control`. */
export function field(labelText, control, hint) {
  const id = control.id || `f-${Math.random().toString(36).slice(2, 9)}`;
  control.id = id;
  const label = h("label", { for: id, text: labelText });
  let hintEl = null;
  if (hint) {
    hintEl = h("p", { class: "hint", id: `${id}-hint`, text: hint });
    control.setAttribute("aria-describedby", hintEl.id);
  }
  const wrap = h("div", { class: "field" }, label, control, hintEl);
  wrap.control = control;
  return wrap;
}

/**
 * A status line that announces changes politely, and errors assertively.
 * `set(text, kind)` where kind is "info" | "ok" | "error" | "busy".
 */
export function statusLine() {
  const polite = h("p", { class: "status", "aria-live": "polite" });
  const alert = h("p", { class: "status error", role: "alert" });
  const wrap = h("div", { class: "status-wrap" }, polite, alert);
  wrap.set = (text, kind = "info") => {
    if (kind === "error") {
      polite.textContent = "";
      alert.textContent = text;
    } else {
      alert.textContent = "";
      polite.textContent = text;
      polite.dataset.kind = kind;
    }
  };
  wrap.clear = () => wrap.set("");
  return wrap;
}

/** Save a Blob as a file. */
export function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const a = h("a", { href: url, download: filename, hidden: true });
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 10_000);
}

/** Copy text to the clipboard, with a fallback for non-secure origins (plain http tunnels). */
export async function copyText(text) {
  if (navigator.clipboard && window.isSecureContext) {
    await navigator.clipboard.writeText(text);
    return;
  }
  const area = h("textarea", { class: "offscreen", readonly: true, "aria-hidden": "true" });
  area.value = text;
  document.body.append(area);
  area.select();
  const ok = document.execCommand("copy");
  area.remove();
  if (!ok) throw new Error("Copy is not available in this browser");
}

/** A copy button that briefly confirms. */
export function copyButton(getText, label = "Copy") {
  const btn = h("button", { type: "button", class: "btn small", text: label });
  btn.addEventListener("click", async () => {
    try {
      await copyText(getText());
      btn.textContent = "Copied";
    } catch {
      btn.textContent = "Copy failed";
    }
    setTimeout(() => (btn.textContent = label), 1600);
  });
  return btn;
}

/** Human-friendly local timestamp. */
export function formatTime(ms) {
  return new Date(ms).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** Compact local timestamp for file names, e.g. 20261018-153012. */
export function fileStamp(date) {
  const p = (n) => String(n).padStart(2, "0");
  return (
    `${date.getFullYear()}${p(date.getMonth() + 1)}${p(date.getDate())}-` +
    `${p(date.getHours())}${p(date.getMinutes())}${p(date.getSeconds())}`
  );
}
