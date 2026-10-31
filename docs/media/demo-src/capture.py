"""Record the Studio scenes of the demo video with Playwright.

Each scene drives a clean headless Chromium (no profile, no tabs, no bookmarks) through the
real Studio of a running Supertonic server and writes, into ``build/capture/``:

- ``<scene>.mp4``  the screen, 2560x1600 (a 1280x800 window at device scale 2), 30 fps
- ``<scene>.json`` when things happened (seconds from the first frame) and every sound the
  page played, saved next to it as ``<scene>-audio-<n>.<ext>`` with its start and end time

The page is shown at http://127.0.0.1:8787 (the default address, so the snippets on Connect
read like a normal install) while every request goes to ``--server``, so the recording never
needs the default port to be free.

Usage: python capture.py --server http://127.0.0.1:8801 speak voices connect ...
Scenes: launch, speak, voices, connect, build-start, build-wait, build-done.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import math
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from playwright.async_api import BrowserContext, Page, Route, async_playwright

HERE = Path(__file__).resolve().parent
OUT = HERE / "build" / "capture"
SHOWN = "http://127.0.0.1:8787"
VIEW = {"width": 1280, "height": 800}
SCALE = 2
FPS = 30
# The maintainer's own recording (not in the repository); see README.md.
REFERENCE = HERE / "build" / "reference" / "my-voice.mp3"

# A visible pointer (headless Chromium draws none) and a hook that reports every sound the
# page plays, with its bytes, so the video gets exactly the audio the Studio produced.
INIT_SCRIPT = r"""
(() => {
  const css = `#demo-cursor{position:fixed;left:0;top:0;width:26px;height:26px;z-index:2147483647;
    pointer-events:none;transform:translate(-100px,-100px);transition:none}
    #demo-cursor svg{filter:drop-shadow(0 2px 3px rgba(0,0,0,.35))}
    .demo-ripple{position:fixed;width:44px;height:44px;margin:-22px 0 0 -22px;border-radius:50%;
    background:rgba(48,80,216,.28);z-index:2147483646;pointer-events:none;
    animation:demo-ripple .5s ease-out forwards}
    @keyframes demo-ripple{from{transform:scale(.3);opacity:1}
      to{transform:scale(1.4);opacity:0}}
    html{scroll-behavior:auto!important}
    *:focus{outline:none!important}`;
  const arrow = `<svg viewBox="0 0 26 26" width="26" height="26">
    <path d="M3 2 L3 21 L8.2 16.2 L11.6 24 L15 22.6 L11.7 15 L19 15 Z" fill="#111" stroke="#fff"
      stroke-width="1.6" stroke-linejoin="round"/></svg>`;
  const ready = () => {
    const style = document.createElement("style");
    style.textContent = css;
    document.head.appendChild(style);
    const c = document.createElement("div");
    c.id = "demo-cursor";
    c.innerHTML = arrow;
    document.body.appendChild(c);
    const move = (e) => (c.style.transform = `translate(${e.clientX - 3}px, ${e.clientY - 2}px)`);
    document.addEventListener("mousemove", move, true);
    document.addEventListener("mousedown", (e) => {
      const r = document.createElement("div");
      r.className = "demo-ripple";
      r.style.left = `${e.clientX}px`;
      r.style.top = `${e.clientY}px`;
      document.body.appendChild(r);
      setTimeout(() => r.remove(), 600);
    }, true);
  };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", ready);
  else ready();

  let n = 0;
  const hooked = new WeakSet();
  const play = HTMLMediaElement.prototype.play;
  HTMLMediaElement.prototype.play = function (...args) {
    const el = this;
    const id = ++n;
    const src = el.src || el.currentSrc;
    if (!hooked.has(el)) {
      hooked.add(el);
      for (const type of ["playing", "pause", "ended"]) {
        el.addEventListener(type, () =>
          window.__demoMedia({ id: el.__demoId, type, t: Date.now() }),
        );
      }
    }
    el.__demoId = id;
    fetch(src)
      .then((r) => r.blob())
      .then((blob) => new Promise((ok) => {
        const fr = new FileReader();
        fr.onload = () => ok({ type: blob.type, data: String(fr.result).split(",")[1] });
        fr.readAsDataURL(blob);
      }))
      .then((b) => window.__demoAudio({ id, t: Date.now(), mime: b.type, data: b.data }));
    return play.apply(this, args);
  };
})();
"""


class Recorder:
    """Frames from the Chrome DevTools screencast, kept with their wall-clock times."""

    def __init__(self, page: Page, name: str) -> None:
        self.page = page
        self.name = name
        self.frames: list[tuple[float, Path]] = []
        self.events: list[dict[str, Any]] = []
        self.audio: dict[int, dict[str, Any]] = {}
        self.dir = OUT / f"{name}-frames"
        shutil.rmtree(self.dir, ignore_errors=True)
        self.dir.mkdir(parents=True)

    async def start(self) -> None:
        self.cdp = await self.page.context.new_cdp_session(self.page)
        self.cdp.on("Page.screencastFrame", self._frame)
        await self.cdp.send(
            "Page.startScreencast",
            {
                "format": "jpeg",
                "quality": 92,
                "maxWidth": VIEW["width"] * SCALE,
                "maxHeight": VIEW["height"] * SCALE,
                "everyNthFrame": 1,
            },
        )

    def _frame(self, params: dict[str, Any]) -> None:
        path = self.dir / f"{len(self.frames):06d}.jpg"
        path.write_bytes(base64.b64decode(params["data"]))
        self.frames.append((float(params["metadata"]["timestamp"]), path))
        asyncio.ensure_future(
            self.cdp.send("Page.screencastFrameAck", {"sessionId": params["sessionId"]})
        )

    def mark(self, label: str) -> None:
        self.events.append({"label": label, "wall": time.time()})
        print(f"  {self.name}: {label}", flush=True)

    def on_media(self, info: dict[str, Any]) -> None:
        entry = self.audio.setdefault(int(info["id"]), {})
        key = {"playing": "start_wall", "pause": "end_wall", "ended": "end_wall"}[info["type"]]
        if key == "start_wall" and "start_wall" in entry:
            return
        entry[key] = info["t"] / 1000

    def on_audio(self, info: dict[str, Any]) -> None:
        entry = self.audio.setdefault(int(info["id"]), {})
        ext = "wav" if "wav" in info["mime"] else "mp3"
        path = OUT / f"{self.name}-audio-{info['id']}.{ext}"
        path.write_bytes(base64.b64decode(info["data"]))
        entry["file"] = path.name

    async def hold(self, seconds: float) -> None:
        """Keep frames coming while nothing moves (the screencast only sends changes)."""
        await self.page.wait_for_timeout(seconds * 1000)

    async def stop(self) -> None:
        await self.page.wait_for_timeout(400)
        await self.cdp.send("Page.stopScreencast")
        await self.page.wait_for_timeout(300)
        t0 = self.frames[0][0]
        end = time.time()
        # Constant frame rate: output frame k shows the newest screencast frame at k / FPS.
        seq = self.dir / "seq"
        seq.mkdir()
        i = 0
        for k in range(int((end - t0) * FPS)):
            t = t0 + k / FPS
            while i + 1 < len(self.frames) and self.frames[i + 1][0] <= t:
                i += 1
            (seq / f"{k:06d}.jpg").hardlink_to(self.frames[i][1])
        video = OUT / f"{self.name}.mp4"
        await asyncio.to_thread(
            subprocess.run,
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-framerate",
                str(FPS),
                "-i",
                str(seq / "%06d.jpg"),
                "-vf",
                "format=yuv420p",
                "-c:v",
                "libx264",
                "-crf",
                "14",
                "-preset",
                "medium",
                "-movflags",
                "+faststart",
                str(video),
            ],
            check=True,
        )
        sounds = []
        for sid, a in sorted(self.audio.items()):
            if "file" not in a or "start_wall" not in a:
                continue
            sounds.append(
                {
                    "id": sid,
                    "file": a["file"],
                    "start": round(a["start_wall"] - t0, 3),
                    "end": round(a["end_wall"] - t0, 3) if "end_wall" in a else None,
                }
            )
        info = {
            "video": video.name,
            "duration": round(end - t0, 3),
            "size": [VIEW["width"] * SCALE, VIEW["height"] * SCALE],
            "events": {e["label"]: round(e["wall"] - t0, 3) for e in self.events},
            "audio": sounds,
        }
        (OUT / f"{self.name}.json").write_text(json.dumps(info, indent=2))
        shutil.rmtree(self.dir)
        print(f"  {self.name}: {info['duration']:.1f} s, {len(sounds)} sounds -> {video.name}")


# ----------------------------------------------------------------------------- helpers
class Pointer:
    """Eased pointer moves, so the cursor glides like a hand on a mouse."""

    def __init__(self, page: Page) -> None:
        self.page = page
        self.x, self.y = VIEW["width"] * 0.62, VIEW["height"] * 0.7

    async def to(self, x: float, y: float, ms: int = 650) -> None:
        steps = max(8, ms // 16)
        x0, y0 = self.x, self.y
        for i in range(1, steps + 1):
            k = i / steps
            e = 0.5 - math.cos(math.pi * k) / 2
            await self.page.mouse.move(x0 + (x - x0) * e, y0 + (y - y0) * e)
            await self.page.wait_for_timeout(16)
        self.x, self.y = x, y

    async def over(self, selector: str, ms: int = 650, dx: float = 0.5, dy: float = 0.5) -> None:
        loc = self.page.locator(selector).first
        await loc.scroll_into_view_if_needed()
        box = await loc.bounding_box()
        assert box, selector
        await self.to(box["x"] + box["width"] * dx, box["y"] + box["height"] * dy, ms)

    async def click(self, selector: str, ms: int = 650, dx: float = 0.5, dy: float = 0.5) -> None:
        await self.over(selector, ms, dx, dy)
        await self.page.wait_for_timeout(120)
        await self.page.mouse.down()
        await self.page.wait_for_timeout(70)
        await self.page.mouse.up()


async def smooth_scroll(page: Page, to_y: float, ms: int = 900) -> None:
    start = await page.evaluate("window.scrollY")
    steps = max(8, ms // 16)
    for i in range(1, steps + 1):
        k = i / steps
        e = 0.5 - math.cos(math.pi * k) / 2
        await page.evaluate(f"window.scrollTo(0, {start + (to_y - start) * e})")
        await page.wait_for_timeout(16)


async def scroll_to(page: Page, selector: str, top: float = 90, ms: int = 900) -> None:
    y = await page.evaluate(
        "([s, top]) => document.querySelector(s).getBoundingClientRect().top"
        " + window.scrollY - top",
        [selector, top],
    )
    await smooth_scroll(page, max(0, y), ms)


async def type_into(page: Page, selector: str, text: str, delay: int = 32) -> None:
    await page.locator(selector).fill("")
    await page.locator(selector).press_sequentially(text, delay=delay)


async def wait_sound_end(rec: Recorder, limit_s: float = 30) -> None:
    """Wait until the last sound the page started has ended."""
    deadline = time.time() + limit_s
    while time.time() < deadline:
        if rec.audio:
            last = rec.audio[max(rec.audio)]
            if "end_wall" in last:
                return
        await rec.page.wait_for_timeout(100)


async def wait_sound_start(rec: Recorder, count: int, limit_s: float = 30) -> None:
    deadline = time.time() + limit_s
    while time.time() < deadline:
        if sum(1 for a in rec.audio.values() if "start_wall" in a) >= count:
            return
        await rec.page.wait_for_timeout(50)
    raise TimeoutError(f"sound {count} did not start")


# ----------------------------------------------------------------------------- scenes
async def scene_launch(page: Page, rec: Recorder, p: Pointer) -> None:
    """The browser opening the Studio for the first time: the welcome card."""
    await page.goto(f"{SHOWN}/#/speak")
    await page.wait_for_selector("#welcome-title")
    await page.wait_for_selector(".server-status:has-text('Ready')")
    rec.mark("loaded")
    await rec.hold(1.2)
    await p.over(".welcome-list li:nth-child(1)", 900)
    await rec.hold(0.6)
    await p.over(".welcome-list li:nth-child(2)", 700)
    await rec.hold(0.6)
    await p.over(".welcome-list li:nth-child(3)", 700)
    await rec.hold(0.8)
    rec.mark("end")


SPEAK_LINES = [
    ("en", "Hi, I'm Mia. I run right here on your computer: no cloud, no account, no waiting."),
    ("ja", "こんにちは、ミアです。日本語も、とても自然に話せます。"),
]


async def scene_speak(page: Page, rec: Recorder, p: Pointer) -> None:
    await page.goto(f"{SHOWN}/#/speak")
    await page.wait_for_selector(".server-status:has-text('Ready')")
    await page.wait_for_function("document.querySelectorAll('.controls select option').length > 20")
    await rec.hold(0.8)
    rec.mark("start")
    for n, (lang, text) in enumerate(SPEAK_LINES, start=1):
        if n == 1:
            await p.click("#script", 700, 0.3, 0.25)
            rec.mark("type-1")
            await type_into(page, "#script", text, 22)
            await rec.hold(0.4)
            await p.over(".controls select >> nth=1", 600, 0.35)
            rec.mark("voice")
            await rec.hold(1.4)
        else:
            await smooth_scroll(page, 0, 600)
            await p.click(".controls select >> nth=2", 600, 0.35)
            await page.locator(".controls select").nth(2).select_option(lang)
            rec.mark(f"language-{n}")
            await rec.hold(0.7)
            await p.click("#script", 600, 0.3, 0.25)
            await page.locator("#script").fill(text)
            rec.mark(f"type-{n}")
            await rec.hold(0.6)
        await p.click(".controls .btn.primary.wide", 600)
        rec.mark(f"generate-{n}")
        await wait_sound_start(rec, n)
        rec.mark(f"playing-{n}")
        await rec.hold(0.3)
        await scroll_to(page, ".result", 330, 700)
        await wait_sound_end(rec)
        rec.mark(f"done-{n}")
        await rec.hold(0.5)
    rec.mark("end")


async def scene_voices(page: Page, rec: Recorder, p: Pointer) -> None:
    await page.goto(f"{SHOWN}/#/voices")
    await page.wait_for_selector(".voice-card")
    await rec.hold(1.0)
    rec.mark("start")
    await smooth_scroll(page, 380, 1600)
    await rec.hold(0.4)
    target = ".voice-card[data-voice-id='M5']"
    await scroll_to(page, target, 260, 1400)
    await p.click(f"{target} .preview-group .btn.icon", 700)
    rec.mark("preview")
    await wait_sound_start(rec, 1)
    rec.mark("playing")
    await wait_sound_end(rec)
    await rec.hold(0.5)
    await smooth_scroll(page, 0, 900)
    await p.over("a[href='#/voices/new']", 700)
    rec.mark("new-voice-button")
    await rec.hold(0.8)
    rec.mark("end")


VOICE_NAME = "My voice"
VOICE_SOURCE = "My own voice, recorded for this demo"


async def scene_build_start(page: Page, rec: Recorder, p: Pointer) -> None:
    await page.goto(f"{SHOWN}/#/voices/new")
    await page.wait_for_selector("#clip-input")
    await rec.hold(1.0)
    rec.mark("start")
    await scroll_to(page, ".clip-drop, #clip-input", 330, 1200)
    await p.over("#clip-input", 700, 0.12)
    await page.locator("#clip-input").set_input_files(str(REFERENCE))
    rec.mark("uploaded")
    await rec.hold(1.6)
    await scroll_to(page, "#step-details", 90, 1000)
    await p.click(".build-form input[type=text] >> nth=0", 600)
    await (
        page.locator(".build-form input[type=text]").nth(0).press_sequentially(VOICE_NAME, delay=45)
    )
    rec.mark("named")
    await p.click(".build-form input[type=text] >> nth=1", 600)
    await page.locator(".build-form input[type=text]").nth(1).fill(VOICE_SOURCE)
    await rec.hold(0.4)
    await p.click("#consent", 600)
    await page.locator("#consent").check()
    rec.mark("consent")
    await rec.hold(0.8)
    await scroll_to(page, "#step-method", 120, 900)
    await p.over(".methods label:nth-of-type(1)", 600, 0.3)
    rec.mark("method")
    await rec.hold(1.2)
    await p.click(".build-form button[type=submit]", 700)
    rec.mark("submit")
    await page.wait_for_selector(".job.panel:not([hidden])", timeout=180_000)
    await page.wait_for_timeout(300)
    await smooth_scroll(page, 0, 500)
    rec.mark("progress")
    await rec.hold(6.0)
    rec.mark("end")


async def scene_build_wait(page: Page, rec: Recorder, p: Pointer) -> None:
    """A still of the progress panel every 20 seconds until the build ends (a time-lapse)."""
    await page.goto(f"{SHOWN}/#/voices/new")
    await page.wait_for_selector(".job.panel:not([hidden])")
    lapse = OUT / "build-lapse"
    lapse.mkdir(exist_ok=True)
    n = len(list(lapse.glob("*.png")))
    while True:
        await page.wait_for_timeout(1500)
        await page.screenshot(path=str(lapse / f"{n:05d}.png"))
        n += 1
        badge = await page.locator(".job .badge").first.text_content()
        if badge and badge.strip() in {"Ready", "Failed", "Cancelled"}:
            print(f"  build ended: {badge}", flush=True)
            break
        await page.wait_for_timeout(18_500)


TRY_TEXT = "Hello! This is my own voice, made from a short recording."


async def scene_build_done(page: Page, rec: Recorder, p: Pointer) -> None:
    """The finished build (the newest job): its Ready panel, Try it, and the voice speaking."""
    await page.goto(f"{SHOWN}/#/voices")
    job = await page.evaluate(
        "fetch('/v1/jobs?limit=1').then((r) => r.json()).then((j) => j.data[0].id)"
    )
    await page.goto(f"{SHOWN}/#/voices/new?job={job}")
    await page.wait_for_selector(".job-result .btn.primary")
    await rec.hold(1.2)
    rec.mark("start")
    await p.over(".job-result .facts", 800)
    await rec.hold(1.0)
    await p.click(".job-result .btn.primary", 700)
    rec.mark("try-it")
    await page.wait_for_selector("#script")
    await rec.hold(0.8)
    await p.click("#script", 600, 0.3, 0.25)
    await page.locator("#script").fill(TRY_TEXT)
    rec.mark("typed")
    await rec.hold(0.8)
    await p.over(".controls select >> nth=1", 600, 0.35)
    await rec.hold(0.8)
    await p.click(".controls .btn.primary.wide", 600)
    rec.mark("generate")
    await wait_sound_start(rec, 1)
    rec.mark("playing")
    await rec.hold(0.3)
    await scroll_to(page, ".result", 330, 700)
    await wait_sound_end(rec)
    await rec.hold(0.6)
    rec.mark("end")


async def scene_connect(page: Page, rec: Recorder, p: Pointer) -> None:
    await page.goto(f"{SHOWN}/#/connect")
    await page.wait_for_selector(".snippet, pre")
    await rec.hold(1.0)
    rec.mark("start")
    await p.over(".connect-top .copy-row .btn", 700)
    await rec.hold(0.5)
    await scroll_to(page, ".snippet", 110, 1100)
    rec.mark("openai")
    await p.click(".snippet .snippet-head .btn", 700)
    rec.mark("copied")
    await rec.hold(1.5)
    await scroll_to(page, ".snippet:nth-child(2)", 110, 1000)
    rec.mark("mcp")
    await rec.hold(1.6)
    await p.click(".more-snippets summary", 700, 0.1)
    await page.wait_for_timeout(200)
    await scroll_to(page, ".more-snippets .snippet:last-child", 110, 1300)
    rec.mark("realtime")
    await rec.hold(2.0)
    rec.mark("end")


SCENES = {
    "launch": scene_launch,
    "speak": scene_speak,
    "voices": scene_voices,
    "connect": scene_connect,
    "build-start": scene_build_start,
    "build-wait": scene_build_wait,
    "build-done": scene_build_done,
}


async def new_context(browser: Any, server: str, welcome: bool) -> BrowserContext:
    ctx: BrowserContext = await browser.new_context(
        viewport=VIEW,
        device_scale_factor=SCALE,
        locale="en-US",
        timezone_id="UTC",
        color_scheme="light",
        permissions=["clipboard-read", "clipboard-write"],
    )

    async def forward(route: Route) -> None:
        url = route.request.url.replace(SHOWN, server, 1)
        # The browser keeps Host and Origin at the shown address, so the server's same-origin
        # checks see one consistent origin.
        await route.continue_(url=url)

    await ctx.route(f"{SHOWN}/**", forward)
    await ctx.add_init_script(INIT_SCRIPT)
    if not welcome:
        await ctx.add_init_script("localStorage.setItem('supertonic.welcomeDismissed', '1')")
    return ctx


async def run(server: str, names: list[str]) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(args=["--autoplay-policy=no-user-gesture-required"])
        for name in names:
            print(f"scene {name}", flush=True)
            ctx = await new_context(browser, server, welcome=name == "launch")
            page = await ctx.new_page()
            rec = Recorder(page, name)
            await page.expose_function("__demoAudio", rec.on_audio)
            await page.expose_function("__demoMedia", rec.on_media)
            pointer = Pointer(page)
            if name == "build-wait":
                await SCENES[name](page, rec, pointer)
            else:
                await page.goto("about:blank")
                await rec.start()
                await SCENES[name](page, rec, pointer)
                await rec.stop()
            await ctx.close()
        await browser.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--server", default="http://127.0.0.1:8801", help="the Supertonic server to record"
    )
    parser.add_argument("scenes", nargs="+", choices=sorted(SCENES))
    args = parser.parse_args()
    asyncio.run(run(args.server.rstrip("/"), args.scenes))


if __name__ == "__main__":
    main()
