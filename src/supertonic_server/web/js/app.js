// Entry point: hash router (#/speak, #/voices, #/connect) and the server status line.

import { stopPreview } from "./audio.js";
import { getHealth, onVoicesChanged } from "./catalog.js";
import * as connect from "./connect.js";
import * as speak from "./speak.js";
import * as voices from "./voices.js";

const SCREENS = { speak, voices, connect };
const TITLES = { speak: "Speak", voices: "Voices", connect: "Connect" };
const mounted = new Set();
let firstRoute = true;

/** Parse "#/voices?x=1" into {name: "voices", params: URLSearchParams}. */
function parseHash() {
  const raw = window.location.hash.replace(/^#\/?/, "");
  const [path, query = ""] = raw.split("?");
  const name = Object.hasOwn(SCREENS, path) ? path : "speak";
  return { name, params: new URLSearchParams(query) };
}

function route() {
  const { name, params } = parseHash();
  stopPreview();
  for (const key of Object.keys(SCREENS)) {
    document.getElementById(`view-${key}`).hidden = key !== name;
  }
  for (const link of document.querySelectorAll(".tabs a")) {
    if (link.dataset.route === name) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  }
  document.title = `${TITLES[name]} | Supertonic Studio`;
  const root = document.getElementById(`view-${name}`);
  if (!mounted.has(name)) {
    SCREENS[name].mount(root);
    mounted.add(name);
  }
  SCREENS[name].show(params);
  // Move focus to the content on navigation (not on first load) for keyboard and screen readers.
  if (!firstRoute) document.getElementById("main").focus({ preventScroll: true });
  firstRoute = false;
}

async function showStatus() {
  const el = document.getElementById("server-status");
  try {
    const info = await getHealth();
    const render = (count) => {
      el.textContent = `${info.model}, ${count} voices, v${info.version}`;
    };
    render(info.voices);
    onVoicesChanged((list) => render(list.length));
    el.dataset.state = "ok";
  } catch (err) {
    el.textContent = `Server unreachable: ${err.message}`;
    el.dataset.state = "error";
  }
}

window.addEventListener("hashchange", route);
route();
showStatus();
