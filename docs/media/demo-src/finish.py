"""Finish the rendered video: loudness, size, the README GIF and the poster.

Usage: python finish.py build/render.mp4
Writes docs/media/demo.mp4, docs/media/demo.gif and docs/media/demo-poster.png.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
MEDIA = HERE.parent
BUILD = HERE / "build"
FF = ["ffmpeg", "-hide_banner", "-y"]
TARGET_LUFS = -16.0
GIF_SECONDS = 12.0
POSTER_AT = 6.4  # the title card, fully drawn (the tag appears with "Free")


def run(args: list[str]) -> str:
    done = subprocess.run(args, check=True, capture_output=True, text=True)
    return done.stderr


def measure(src: Path) -> dict[str, str]:
    log = run(
        [
            *FF,
            "-i",
            str(src),
            "-af",
            f"loudnorm=I={TARGET_LUFS}:TP=-2.0:LRA=11:print_format=json",
            "-f",
            "null",
            "-",
        ]
    )
    found = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", log, re.S)
    assert found, "loudnorm printed no measurement"
    data: dict[str, str] = json.loads(found.group(0))
    return data


def main() -> None:
    src = Path(sys.argv[1]).resolve()
    m = measure(src)
    norm = (
        f"loudnorm=I={TARGET_LUFS}:TP=-2.0:LRA=11"
        f":measured_I={m['input_i']}:measured_TP={m['input_tp']}"
        f":measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}"
        f":offset={m['target_offset']}:linear=true"
    )
    mp4 = MEDIA / "demo.mp4"
    run(
        [
            *FF,
            "-i",
            str(src),
            "-af",
            f"{norm},aresample=48000",
            "-c:v",
            "libx264",
            "-preset",
            "slow",
            "-crf",
            "25",
            "-tune",
            "animation",
            "-pix_fmt",
            "yuv420p",
            "-profile:v",
            "high",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-movflags",
            "+faststart",
            str(mp4),
        ]
    )
    edit = json.loads((BUILD / "edit.json").read_text())
    start = edit["marks"]["speak"]
    gif = MEDIA / "demo.gif"
    palette = BUILD / "palette.png"
    clip = "fps=12,scale=800:-1:flags=lanczos"
    run(
        [
            *FF,
            "-ss",
            f"{start:.2f}",
            "-t",
            str(GIF_SECONDS),
            "-i",
            str(src),
            "-vf",
            f"{clip},palettegen=max_colors=128:stats_mode=diff",
            str(palette),
        ]
    )
    run(
        [
            *FF,
            "-ss",
            f"{start:.2f}",
            "-t",
            str(GIF_SECONDS),
            "-i",
            str(src),
            "-i",
            str(palette),
            "-lavfi",
            f"{clip}[x];[x][1:v]paletteuse=dither=bayer:bayer_scale=4:diff_mode=rectangle",
            "-loop",
            "0",
            str(gif),
        ]
    )
    poster = MEDIA / "demo-poster.png"
    run(
        [
            *FF,
            "-ss",
            str(POSTER_AT),
            "-i",
            str(src),
            "-frames:v",
            "1",
            "-vf",
            "scale=1280:-1",
            str(poster),
        ]
    )
    for f in (mp4, gif, poster):
        print(f"{f.relative_to(MEDIA.parent.parent)}: {f.stat().st_size / 1e6:.2f} MB")


if __name__ == "__main__":
    main()
