# Voice builder

The voice builder turns a reference recording into a new Supertonic 3 voice style on a
CUDA machine (install with `uv sync --extra builder`). The full guide (methods, setup,
forwarding, troubleshooting) is still being written; this page starts with the knobs.

## Methods

- `accurate` (default): picks the nearest shipped preset by ECAPA speaker similarity, then
  optimises `style_ttl` with Adam against that similarity for up to 3000 steps (about
  1.8 s per step on an RTX 4050 Laptop GPU, so up to ~90 min), and finally matches the
  reference speaking rate by inverting `style_dp`. The ECAPA model
  (`speechbrain/spkrec-ecapa-voxceleb`) is downloaded on first use into
  `<Hugging Face hub cache>/supertonic-ecapa` (for example
  `~/.cache/huggingface/hub/supertonic-ecapa`; `HF_HUB_CACHE` / `HF_HOME` move it).
- `fast`: supertonic.embed's WavLM-statistics inversion (minutes, lower similarity).

## Debugging knobs

| Variable | Default | Effect |
|---|---|---|
| `SUPERTONIC_BUILDER_ACCURATE_STEPS` | unset (3000) | Caps the `accurate` descent at this many steps, for quick test builds. A positive integer; anything else fails the build. Read by the builder worker process. |
