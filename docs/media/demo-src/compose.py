"""Cut the captured scenes, narration and title cards into a HyperFrames project.

Usage: python compose.py           writes build/project/ (index.html and its media)
Then:  see README.md for the render and finishing commands.

The edit is described below as a list of shots in the order they play. Shot times come from
the events each capture logged (build/capture/<scene>.json), so a re-captured scene keeps
its cuts in the right places.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from html import escape
from pathlib import Path
from string import Template
from typing import Any

HERE = Path(__file__).resolve().parent
BUILD = HERE / "build"
CAP = BUILD / "capture"
NARR = BUILD / "narration"
PROJECT = BUILD / "project"
# The maintainer's own recording (not in the repository): the same file capture.py uploads.
REFERENCE = BUILD / "reference" / "my-voice.mp3"
REFERENCE_PLAY = "reference/my-voice-play.wav"  # a loudness-matched copy for the video
REF_IN, REF_LEN = 0.95, 3.5  # the part of it the video plays

W, H = 1920, 1080
# The browser window: its page area shows the 1280x800 Studio at 1.125x.
VIEW_W, VIEW_H = 1440, 900
PAGE_W, PAGE_H = 1280, 800
K = VIEW_W / PAGE_W
FADE = 0.3
# What the new voice says in the last build scene (capture.py types the same text).
TRY_TEXT = "Hello! This is my own voice, made from a short recording."
INTRO_AT = 0.5


def scene(name: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((CAP / f"{name}.json").read_text())
    return data


def sound_length(path: Path) -> float:
    """A sound file's length in seconds (the page's own end events can arrive late)."""
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return float(out)


def narration() -> dict[str, Any]:
    data: dict[str, Any] = json.loads((NARR / "timings.json").read_text())
    return data


def spoken_line(line: str) -> str:
    """A caption line as the narrator says it (see `say` in narration.json)."""
    say: dict[str, str] = json.loads((HERE / "narration.json").read_text(encoding="utf-8"))["say"]
    for written, sound in say.items():
        line = line.replace(written, sound)
    return line


@dataclass
class Zoom:
    """At `at` s into the shot, take `dur` s to reach `scale`, centred on page point (fx, fy)."""

    at: float
    scale: float
    fx: float = PAGE_W / 2
    fy: float = PAGE_H / 2
    dur: float = 0.9


@dataclass
class Shot:
    src: str  # media file in the project
    start: float  # timeline time
    media_in: float
    length: float
    zooms: list[Zoom] = field(default_factory=list)
    kind: str = "video"  # video | image
    fade_in: bool = True


@dataclass
class Edit:
    t: float = 0.0
    shots: list[Shot] = field(default_factory=list)
    captions: list[tuple[float, float, str, str]] = field(
        default_factory=list
    )  # start, end, text, style
    sounds: list[tuple[float, str, float, float, float]] = field(
        default_factory=list
    )  # start, src, in, len, vol
    chips: list[tuple[float, float, str, str]] = field(default_factory=list)  # + position
    cards: dict[str, tuple[float, float]] = field(default_factory=dict)
    window: list[tuple[float, float]] = field(default_factory=list)
    marks: dict[str, float] = field(default_factory=dict)

    def shot(
        self,
        src: str,
        media_in: float,
        media_out: float,
        zooms: list[Zoom] | None = None,
        kind: str = "video",
        fade_in: bool = True,
    ) -> Shot:
        s = Shot(src, self.t, media_in, media_out - media_in, zooms or [], kind, fade_in)
        self.shots.append(s)
        self.t += s.length
        return s

    def narrate(self, key: str, at: float, lines: list[str] | None = None) -> float:
        """Narration line `key` at timeline `at`, captioned in `lines` (default: one line)."""
        info = narration()[key]
        dur = float(info["duration_ms"]) / 1000
        self.sounds.append((at, f"narration/{key}.wav", 0.0, dur, 1.0))
        self.caption_words(at, info, lines or [info["text"]])
        return at + dur

    def caption_words(self, at: float, info: dict[str, Any], lines: list[str]) -> None:
        """Split a narration caption into `lines`, timed by the word timings."""
        words = info["words"]
        dur = info["duration_ms"] / 1000
        i = 0
        for n, line in enumerate(lines):
            count = len(spoken_line(line).split())
            first = words[min(i, len(words) - 1)]["start_ms"] / 1000
            start = 0.0 if n == 0 else first
            i += count
            end = dur if n == len(lines) - 1 else words[min(i, len(words) - 1)]["start_ms"] / 1000
            self.captions.append(
                (at + start - 0.05, at + end + (0.25 if n == len(lines) - 1 else 0), line, "narr")
            )

    def ui_sound(self, scene_name: str, shot: Shot, index: int, text: str, note: str = "") -> None:
        """A sound the Studio played during `shot`, placed where it played and captioned."""
        a = scene(scene_name)["audio"][index]
        at = shot.start + (a["start"] - shot.media_in)
        length = sound_length(CAP / a["file"])
        self.sounds.append((at, f"capture/{a['file']}", 0.0, length, 1.0))
        self.captions.append((at, at + length + 0.2, text, "ui"))
        if note:
            self.captions.append((at, at + length + 0.2, note, "note"))


def build_edit() -> Edit:
    e = Edit()

    # 1. Title card -------------------------------------------------------------------
    e.cards["title"] = (0.0, 6.9)
    e.narrate(
        "intro",
        INTRO_AT,
        [
            "Meet Supertonic Server: natural speech in thirty-one languages,",
            "on your own computer. Free and open source.",
        ],
    )
    e.t = 6.9

    # 2. Double-click launcher -> Studio --------------------------------------------------
    e.cards["finder"] = (e.t, 1.9)
    e.cards["terminal"] = (e.t + 1.6, 3.0)
    e.narrate(
        "launch",
        e.t + 0.25,
        [
            "Double-click the start file.",
            "It installs what it needs and opens the Studio in your browser.",
        ],
    )
    e.t += 4.4
    win_start = e.t
    launch = scene("launch")
    e.shot(
        "capture/launch.mp4",
        0.2,
        min(launch["duration"] - 0.1, 4.0),
        [Zoom(0.5, 1.18, 640, 420, 2.4)],
    )

    # 3. Speak: English, then the same voice in Japanese -----------------------------------
    sp = scene("speak")
    ev = sp["events"]
    e.marks["speak"] = e.t
    a1 = e.shot(
        "capture/speak.mp4",
        ev["start"] - 0.2,
        ev["generate-1"] + 0.55,
        [
            Zoom(0.5, 1.45, 420, 300, 0.9),
            Zoom(ev["voice"] - ev["start"] - 0.1, 1.5, 1000, 330, 0.8),
            Zoom(ev["generate-1"] - ev["start"] - 0.6, 1.0, dur=0.6),
        ],
    )
    e.narrate("speak", a1.start + 0.5, ["Type anything, pick a voice, and press Generate."])
    a2 = e.shot(
        "capture/speak.mp4",
        ev["playing-1"] - 0.35,
        ev["done-1"] + 0.45,
        [Zoom(0.0, 1.0), Zoom(0.6, 1.2, 615, 400, 0.9)],
    )
    e.ui_sound(
        "speak",
        a2,
        0,
        "“Hi, I'm Mia. I run right here on your computer: no cloud, no account, no waiting.”",
    )
    b1 = e.shot(
        "capture/speak.mp4",
        ev["language-2"] - 1.25,
        ev["generate-2"] + 0.5,
        [
            Zoom(0.0, 1.0),
            Zoom(0.5, 1.5, 1000, 420, 0.8),
            Zoom(2.5, 1.4, 470, 300, 0.8),
            Zoom(ev["generate-2"] - ev["language-2"] + 0.4, 1.0, dur=0.6),
        ],
    )
    e.narrate("languages", b1.start + 0.3, ["The same voice speaks every language."])
    b2 = e.shot(
        "capture/speak.mp4",
        ev["playing-2"] - 0.3,
        ev["done-2"] + 0.5,
        [Zoom(0.0, 1.0), Zoom(0.5, 1.2, 615, 400, 0.9)],
    )
    e.ui_sound(
        "speak",
        b2,
        1,
        "“こんにちは、ミアです。日本語も、とても自然に話せます。”",
        "Japanese: “Hello, I'm Mia. I speak Japanese very naturally, too.”",
    )

    # 4. Voices ---------------------------------------------------------------------------
    vo = scene("voices")
    ev = vo["events"]
    v_in = ev["preview"] - 4.0
    v1 = e.shot(
        "capture/voices.mp4",
        v_in,
        ev["playing"] + 3.3,
        [Zoom(0.0, 1.0), Zoom(ev["preview"] - v_in - 0.9, 1.45, 330, 520, 0.9)],
    )
    e.narrate("voices", v1.start + 0.25, ["Ten built-in voices, each with a name and a style."])
    e.ui_sound("voices", v1, 0, "Omar: “The quick brown fox jumps over the lazy dog.”")

    # 5. Your own voice ---------------------------------------------------------------------
    bs = scene("build-start")
    ev = bs["events"]
    c1 = e.shot(
        "capture/build-start.mp4",
        ev["start"] - 0.3,
        ev["uploaded"] + 1.3,
        [Zoom(0.0, 1.0), Zoom(ev["uploaded"] - ev["start"] - 1.2, 1.35, 470, 420, 0.9)],
    )
    e.narrate(
        "clone", c1.start + 0.2, ["Or make a voice of your own from about half a minute of speech."]
    )
    hold = REF_LEN + 0.15
    e.shot(
        "stills/uploaded.png",
        0,
        hold,
        [Zoom(0.0, 1.35, 470, 420, 0.1), Zoom(0.2, 1.5, 470, 470, REF_LEN)],
        kind="image",
        fade_in=False,
    )
    ref_at = c1.start + c1.length + 0.15
    e.sounds.append((ref_at, REFERENCE_PLAY, REF_IN, REF_LEN, 1.0))
    e.captions.append(
        (ref_at, ref_at + REF_LEN + 0.1, "▶ The recording: my own voice, 36 seconds", "ui")
    )
    fast = e.shot(
        "capture/build-start-fast.mp4",
        0.0,
        fast_length(ev),
        [
            Zoom(0.0, 1.3, 470, 380, 0.6),
            Zoom(fast_at(ev, "consent") - 0.5, 1.3, 470, 400, 0.8),
            Zoom(fast_at(ev, "method") - 0.3, 1.35, 470, 420, 0.8),
            Zoom(fast_at(ev, "submit") - 0.8, 1.0, dur=0.6),
        ],
    )
    e.narrate(
        "build",
        fast.start + 0.3,
        ["Confirm you have permission, choose Best match,", "and build it on a graphics card."],
    )
    lapse = e.shot(
        "capture/build-lapse.mp4", 0.0, lapse_length(), [Zoom(0.0, 1.45, 500, 540, 0.01)]
    )
    e.chips.append(
        (
            lapse.start + 0.2,
            lapse.start + lapse.length - 0.1,
            "⏩  Sped up: about 1½ hours on a laptop graphics card",
            "band",
        )
    )
    if (CAP / "build-done.json").exists():
        build_done(e)
    else:
        print("note: no build-done capture yet; the edit skips the finished voice")

    # 6. Connect ---------------------------------------------------------------------------
    co = scene("connect")
    ev = co["events"]
    k1 = e.shot(
        "capture/connect.mp4",
        ev["start"] - 0.3,
        ev["mcp"] + 1.1,
        [
            Zoom(0.0, 1.0),
            Zoom(ev["openai"] - ev["start"] - 0.3, 1.3, 600, 300, 0.9),
            Zoom(ev["mcp"] - ev["start"], 1.3, 600, 250, 0.9),
        ],
    )
    k2 = e.shot(
        "capture/connect.mp4",
        ev["realtime"] - 0.9,
        ev["realtime"] + 1.3,
        [Zoom(0.0, 1.3, 600, 560, 0.01)],
    )
    e.narrate(
        "connect",
        k1.start + 0.4,
        [
            "Plug it into your apps: an OpenAI-compatible API,",
            "tools for AI agents, and realtime streaming.",
        ],
    )
    e.chips.append(
        (
            k1.start + ev["openai"] - ev["start"] + 0.9,
            k2.start + k2.length - 0.2,
            "Drop-in for OpenAI text-to-speech\nEasy switch from ElevenLabs",
            "side",
        )
    )
    e.window.append((win_start, e.t))

    # 7. End card --------------------------------------------------------------------------
    e.cards["end"] = (e.t - FADE, 4.0)
    e.narrate("outro", e.t + 0.3, ["Supertonic Server. Free, open source, and it runs offline."])
    e.t += 4.0 - FADE
    return e


def build_done(e: Edit) -> None:
    """The finished build: the Ready panel, Try it, and the new voice speaking."""
    done = scene("build-done")
    ev = done["events"]
    d1 = e.shot(
        "capture/build-done.mp4",
        ev["start"] + 0.1,
        ev["try-it"] + 0.2,
        [Zoom(0.0, 1.5, 450, 330, 0.01)],
    )
    e.narrate("ready", d1.start + 0.4, ["And here it is."])
    d3 = e.shot(
        "capture/build-done.mp4",
        ev["playing"] - 0.3,
        done["audio"][0]["start"] + sound_length(CAP / done["audio"][0]["file"]) + 0.4,
        [Zoom(0.0, 1.0), Zoom(0.5, 1.2, 615, 400, 0.9)],
    )
    e.ui_sound(
        "build-done",
        d3,
        0,
        f"“{TRY_TEXT}”",
        "The new voice, “My voice”, built from that recording",
    )


# --- the sped-up form fill and the time-lapse -------------------------------------------------
FORM_SPEED = 2.0


def fast_length(ev: dict[str, float]) -> float:
    return (ev["submit"] + 0.9 - (ev["uploaded"] + 1.3)) / FORM_SPEED


def fast_at(ev: dict[str, float], label: str) -> float:
    return (ev[label] - (ev["uploaded"] + 1.3)) / FORM_SPEED


LAPSE_SECONDS = 3.5


def lapse_length() -> float:
    return LAPSE_SECONDS


def prepare_media() -> None:
    """Media that is derived from the captures: the sped-up form, the lapse, a still."""
    ev = scene("build-start")["events"]
    stills = PROJECT / "stills"
    stills.mkdir(parents=True, exist_ok=True)
    ff = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"]
    subprocess.run(
        [
            *ff,
            "-ss",
            f"{ev['uploaded'] + 1.25:.3f}",
            "-i",
            str(CAP / "build-start.mp4"),
            "-frames:v",
            "1",
            str(stills / "uploaded.png"),
        ],
        check=True,
    )
    start = ev["uploaded"] + 1.3
    subprocess.run(
        [
            *ff,
            "-ss",
            f"{start:.3f}",
            "-to",
            f"{ev['submit'] + 0.9:.3f}",
            "-i",
            str(CAP / "build-start.mp4"),
            "-vf",
            f"setpts=PTS/{FORM_SPEED},fps=30,format=yuv420p",
            "-an",
            "-c:v",
            "libx264",
            "-crf",
            "14",
            str(PROJECT / "capture" / "build-start-fast.mp4"),
        ],
        check=True,
    )
    subprocess.run(
        [
            *ff,
            "-i",
            str(REFERENCE),
            "-ac",
            "1",
            "-ar",
            "44100",
            "-af",
            "loudnorm=I=-18:TP=-2",
            str(PROJECT / REFERENCE_PLAY),
        ],
        check=True,
    )
    frames = sorted((CAP / "build-lapse").glob("*.png"))
    want = int(LAPSE_SECONDS * 30)
    pick = [frames[round(i * (len(frames) - 1) / max(1, want - 1))] for i in range(want)]
    seq = BUILD / "lapse-seq"
    shutil.rmtree(seq, ignore_errors=True)
    seq.mkdir()
    for i, f in enumerate(pick):
        (seq / f"{i:05d}.png").hardlink_to(f)
    subprocess.run(
        [
            *ff,
            "-framerate",
            "30",
            "-i",
            str(seq / "%05d.png"),
            "-vf",
            "format=yuv420p",
            "-c:v",
            "libx264",
            "-crf",
            "14",
            str(PROJECT / "capture" / "build-lapse.mp4"),
        ],
        check=True,
    )


# --- HTML -------------------------------------------------------------------------------------
LOGO = "M3 16c3-9 5-9 7 0s4 9 7 0 5-9 8 0 3 4 4 4"
POINTER = "M3 2 L3 21 L8.2 16.2 L11.6 24 L15 22.6 L11.7 15 L19 15 Z"
FINDER_FILES = [
    ("folder", "docs"),
    ("folder", "scripts"),
    ("folder", "src"),
    ("app", "Start Supertonic.command"),
    ("doc", "Start Supertonic.bat"),
    ("doc", "start-supertonic.sh"),
    ("doc", "README.md"),
    ("doc", "LICENSE"),
]
# What the macOS launcher printed on a first start (scripts/launch.sh), shown on the default port.
TERMINAL = [
    ("dim", "== Supertonic"),
    ("", "Installing Supertonic (the first time this takes a minute or two)."),
    ("dim", "Installed 77 packages in 367ms"),
    ("", "Starting Supertonic. The first start downloads the voice model (about 400 MB),"),
    ("", "which can take a few minutes. Later starts take a few seconds."),
    ("ok", "Supertonic is ready: http://127.0.0.1:8787/"),
    ("", "Keep this window open while you use it. To stop Supertonic, close this window"),
    ("", "or press Ctrl+C."),
]
OUT3 = {"ease": "power3.out"}


def tw(method: str, target: str, at: float, *values: dict[str, Any]) -> str:
    """One GSAP call on the root timeline at `at` seconds."""
    args = ", ".join(json.dumps(v) for v in values)
    return f"tl.{method}({json.dumps(target)}, {args}, {at:.3f});"


def timed(
    tag: str, ident: str, start: float, length: float, attrs: str = "", body: str = ""
) -> str:
    """An element HyperFrames shows from `start` for `length` seconds."""
    extra = f" {attrs}" if attrs else ""
    return (
        f'<{tag} id="{ident}"{extra} data-start="{start:.3f}" data-duration="{length:.3f}">'
        f"{body}</{tag}>"
    )


def zoom_tweens(shot_id: str, shot: Shot) -> list[str]:
    out = []
    for i, z in enumerate(shot.zooms):
        nxt = shot.zooms[i + 1].at if i + 1 < len(shot.zooms) else shot.length
        dur = max(0.01, min(z.dur, nxt - z.at - 0.02))
        s = z.scale
        x = min(0.0, max(VIEW_W - s * VIEW_W, VIEW_W / 2 - s * K * z.fx))
        y = min(0.0, max(VIEW_H - s * VIEW_H, VIEW_H / 2 - s * K * z.fy))
        move = {"x": round(x, 1), "y": round(y, 1), "scale": round(s, 3)}
        out.append(
            tw(
                "to",
                f"#{shot_id} .zoom",
                shot.start + z.at,
                {**move, "duration": round(dur, 2), "ease": "power2.inOut"},
            )
        )
    return out


def shot_parts(e: Edit) -> tuple[list[str], list[str]]:
    """The shots inside the browser window, and their cuts, fades and zooms."""
    html_parts: list[str] = []
    js: list[str] = []
    for n, s in enumerate(e.shots):
        sid = f"shot{n}"
        lead = FADE if s.fade_in and n else 0.0
        start, length = s.start - lead, s.length + lead
        if s.kind == "video":
            media_start = max(0.0, s.media_in - lead)
            attrs = f'src="{s.src}" muted playsinline data-media-start="{media_start:.3f}"'
            media = timed("video", f"{sid}v", start, length, attrs)
        else:
            media = f'<img src="{s.src}" alt="">'
        html_parts.append(f'<div id="{sid}" class="shot"><div class="zoom">{media}</div></div>')
        if lead:
            js.append(
                tw(
                    "fromTo",
                    f"#{sid}",
                    start,
                    {"opacity": 0},
                    {"opacity": 1, "duration": FADE, "ease": "none"},
                )
            )
        else:
            js.append(tw("set", f"#{sid}", start, {"opacity": 1}))
        js.append(tw("set", f"#{sid}", start + length, {"opacity": 0}))
        js.extend(zoom_tweens(sid, s))
    w0, w1 = e.window[0]
    js.append(
        tw(
            "fromTo",
            "#window",
            w0 - 0.5,
            {"opacity": 0, "y": 40, "scale": 0.94},
            {"opacity": 1, "y": 0, "scale": 1, "duration": 0.6, **OUT3},
        )
    )
    js.append(
        tw(
            "to",
            "#window",
            w1 - 0.5,
            {"opacity": 0, "scale": 0.97, "duration": 0.5, "ease": "power2.in"},
        )
    )
    return html_parts, js


def card_script(e: Edit) -> list[str]:
    """The title, launcher and end cards' entrances and exits."""
    t0, d = e.cards["title"]
    words = narration()["intro"]["words"]
    free_at = next(w["start_ms"] for w in words if w["text"] == "Free") / 1000
    pop = {"opacity": 0, "scale": 0.6, "duration": 0.7, "ease": "back.out(1.7)"}
    js = [
        tw("from", "#title .logo", t0 + 0.2, pop),
        tw("from", "#title h1", t0 + 0.4, {"opacity": 0, "y": 30, "duration": 0.7, **OUT3}),
        tw("from", "#title .lead", t0 + 1.2, {"opacity": 0, "y": 20, "duration": 0.6, **OUT3}),
        tw(
            "from",
            "#title .tag",
            t0 + INTRO_AT + free_at,
            {"opacity": 0, "y": 14, "duration": 0.6, **OUT3},
        ),
        tw("to", "#title", t0 + d - 0.5, {"opacity": 0, "duration": 0.5}),
    ]
    f0, fd = e.cards["finder"]
    js += [
        tw("from", "#finder", f0, {"opacity": 0, "y": 30, "duration": 0.45, **OUT3}),
        tw(
            "fromTo",
            "#finder .pointer",
            f0 + 0.25,
            {"x": 520, "y": 330},
            {"x": 300, "y": 150, "duration": 0.8, "ease": "power2.inOut"},
        ),
        tw(
            "to",
            "#finder .target",
            f0 + 1.1,
            {"backgroundColor": "rgba(48,80,216,0.35)", "duration": 0.08},
        ),
        tw(
            "to",
            "#finder .pointer",
            f0 + 1.1,
            {"scale": 0.85, "duration": 0.07, "yoyo": True, "repeat": 3},
        ),
        tw("to", "#finder", f0 + fd - 0.35, {"opacity": 0, "scale": 0.97, "duration": 0.35}),
    ]
    t1, td = e.cards["terminal"]
    js.append(tw("from", "#terminal", t1, {"opacity": 0, "scale": 0.9, "duration": 0.35, **OUT3}))
    for i in range(len(TERMINAL)):
        js.append(
            tw(
                "from",
                f"#terminal .ln:nth-child({i + 1})",
                t1 + 0.25 + i * 0.22,
                {"opacity": 0, "duration": 0.05},
            )
        )
    js.append(tw("to", "#terminal", t1 + td - 0.4, {"opacity": 0, "y": -20, "duration": 0.4}))
    e0, _ = e.cards["end"]
    js += [
        tw("from", "#end", e0, {"opacity": 0, "duration": 0.5}),
        tw("from", "#end .logo", e0 + 0.2, pop),
        tw("from", "#end h1", e0 + 0.35, {"opacity": 0, "y": 30, "duration": 0.7, **OUT3}),
        tw("from", "#end .url", e0 + 0.9, {"opacity": 0, "y": 20, "duration": 0.6, **OUT3}),
        tw("from", "#end .tag", e0 + 1.4, {"opacity": 0, "y": 14, "duration": 0.6, **OUT3}),
    ]
    return js


def overlay_parts(e: Edit) -> tuple[list[str], list[str]]:
    """Chips, captions and sounds."""
    html_parts: list[str] = []
    js: list[str] = []
    for n, (c0, c1, text, pos) in enumerate(e.chips):
        body = escape(text).replace("\n", "<br>")
        html_parts.append(timed("div", f"chip{n}", c0, c1 - c0, f'class="chip {pos} clip"', body))
        js.append(tw("from", f"#chip{n}", c0, {"opacity": 0, "y": -16, "duration": 0.4, **OUT3}))
        js.append(tw("to", f"#chip{n}", c1 - 0.3, {"opacity": 0, "duration": 0.3}))
    main = sorted((c for c in e.captions if c[3] != "note"), key=lambda c: c[0])
    for n, (c0, c1, text, style) in enumerate(main):
        end = min(c1, main[n + 1][0]) if n + 1 < len(main) else min(c1, e.t)
        body = f"<span>{escape(text)}</span>"
        html_parts.append(timed("div", f"cap{n}", c0, end - c0, f'class="cap {style} clip"', body))
    notes = [c for c in e.captions if c[3] == "note"]
    for n, (c0, c1, text, _) in enumerate(notes):
        body = f"<span>{escape(text)}</span>"
        html_parts.append(timed("div", f"note{n}", c0, c1 - c0, 'class="note clip"', body))
    for n, (s0, src, media_in, length, vol) in enumerate(e.sounds):
        attrs = f'src="{src}" data-media-start="{media_in:.3f}" data-volume="{vol}"'
        html_parts.append(timed("audio", f"snd{n}", s0, length, attrs))
    return html_parts, js


def html(e: Edit) -> str:
    shots, shot_js = shot_parts(e)
    overlays, overlay_js = overlay_parts(e)
    files = "".join(
        f'<div class="file {kind}{" target" if "command" in name else ""}"><i></i>'
        f"<span>{escape(name)}</span></div>"
        for kind, name in FINDER_FILES
    )
    terminal = "".join(f'<div class="ln {c}">{escape(t)}</div>' for c, t in TERMINAL)
    cards = {
        f"{name}_{part}": f"{value:.3f}"
        for name, (start, length) in e.cards.items()
        for part, value in (("start", start), ("length", length))
    }
    page = Template((HERE / "template.html").read_text(encoding="utf-8"))
    return page.substitute(
        width=W,
        height=H,
        duration=f"{e.t:.3f}",
        css=(HERE / "style.css").read_text(encoding="utf-8"),
        logo=LOGO,
        pointer=POINTER,
        files=files,
        terminal=terminal,
        shots="\n".join(shots),
        overlays="\n".join(overlays),
        script="\n".join([*shot_js, *card_script(e), *overlay_js]),
        **cards,
    )


def link(src: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        dest.unlink()
    os.link(src, dest)


def main() -> None:
    shutil.rmtree(PROJECT, ignore_errors=True)
    (PROJECT / "capture").mkdir(parents=True)
    for f in CAP.glob("*.mp4"):
        link(f, PROJECT / "capture" / f.name)
    for f in CAP.glob("*-audio-*"):
        link(f, PROJECT / "capture" / f.name)
    for f in (p for p in NARR.glob("*.wav") if not p.name.endswith(".raw.wav")):
        link(f, PROJECT / "narration" / f.name)
    link(REFERENCE, PROJECT / "reference" / REFERENCE.name)
    prepare_media()
    edit = build_edit()
    (PROJECT / "index.html").write_text(html(edit), encoding="utf-8")
    (BUILD / "edit.json").write_text(
        json.dumps({"duration": edit.t, "marks": edit.marks}, indent=2)
    )
    (PROJECT / "meta.json").write_text(
        json.dumps({"id": "supertonic-demo", "name": "Supertonic demo"})
    )
    print(
        f"wrote {PROJECT / 'index.html'}: {edit.t:.1f} s, {len(edit.shots)} shots, "
        f"{len(edit.sounds)} sounds, {len(edit.captions)} captions"
    )


if __name__ == "__main__":
    main()
