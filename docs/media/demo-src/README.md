# Demo video source

Everything needed to make `docs/media/demo.mp4`, `demo.gif` and `demo-poster.png` again.
The screen recordings are real: a clean headless Chromium drives the Studio of a running
Supertonic server. The narration is spoken by Supertonic itself (the built-in voice Nora),
and every sound in the Studio scenes is the audio the Studio actually produced.

| File | What it does |
|---|---|
| `capture.py` | Records the Studio scenes with Playwright (`build/capture/<scene>.mp4` + timings + the audio the page played) |
| `narrate.py` | Speaks the lines in `narration.json` through `/v1/tts/timestamps` and tightens the pauses |
| `compose.py` | Cuts scenes, narration, captions and cards into a [HyperFrames](https://github.com/heygen-com/hyperframes) project (`build/project/`) |
| `template.html`, `style.css` | The page HyperFrames renders: title and end cards, the browser window, captions |
| `finish.py` | Loudness to -16 LUFS, H.264/AAC with faststart, the README GIF and the poster |

The repository's mypy configuration covers only `src/`; these scripts also pass
`mypy --strict` when Playwright is installed (`uv run --with playwright mypy --strict *.py`).

Everything generated goes to `build/` (git-ignored).

## Needs

- uv, Node.js 22 or newer (for `npx`), ffmpeg and ffprobe.
- Playwright for Python and its Chromium: `uv run --with playwright playwright install chromium`.
- A Supertonic server for the recording. For the "your own voice" scene it must be able to
  build voices (an NVIDIA GPU, or `SUPERTONIC_BUILDER_URL` pointing at one), and a
  "Best match" build takes about 1½ hours.

## Commands

Run from this folder. Start a scratch server with its own data folder on a spare port
(8801 here). The recording shows the page at the default address `http://127.0.0.1:8787`
while sending every request to the scratch server, so that origin must be allowed:

```bash
SUPERTONIC_DATA_DIR="$PWD/build/data" SUPERTONIC_PORT=8801 \
SUPERTONIC_ALLOWED_ORIGINS=http://127.0.0.1:8787 \
  uv run --project ../../.. supertonic-server serve
```

The new voice in the video is built from the maintainer's own recording: 36 seconds of
reading the Studio's English sample text. It is not included in the repository. To make the
video again, record yourself the same way (or use any recording you have the right to use)
and save it as `build/reference/my-voice.mp3`; that file is what the upload scene picks and
what the video plays a few seconds of.

Record, in this order (`build-start` starts the real build; `build-wait` takes a still of
the progress every 20 seconds until it is done; `build-done` needs the finished voice):

```bash
PW="uv run --with playwright python"
$PW capture.py --server http://127.0.0.1:8801 launch speak voices connect
$PW capture.py --server http://127.0.0.1:8801 build-start
$PW capture.py --server http://127.0.0.1:8801 build-wait
$PW capture.py --server http://127.0.0.1:8801 build-done
python3 narrate.py --server http://127.0.0.1:8801
python3 compose.py
cd build/project
DO_NOT_TRACK=1 npx --yes hyperframes@0.8.146 lint
DO_NOT_TRACK=1 npx --yes hyperframes@0.8.146 render --output ../render.mp4 --fps 30 \
  --quality high --video-frame-format png
cd ../..
python3 finish.py build/render.mp4
```

`npx --yes hyperframes@0.8.146 snapshot --at 5,30,60 --no-end` in `build/project` saves
stills for a quick look without a full render.

## Notes

- The launcher scene's terminal text is what `scripts/launch.sh` printed on a first start,
  with the port shown as the default 8787; the folder window is drawn, not recorded, so
  no real desktop appears in the video.
- Waiting for the speech to be generated (one to two seconds) and the form filling are
  shortened or sped up; the build progress is a time-lapse of the real 1½-hour build.
- The narration pauses between sentences are capped at half a second by `narrate.py`; the
  speech itself is not changed.
