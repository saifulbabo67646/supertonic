# Voice builder

The voice builder turns a reference recording into a new Supertonic 3 voice style on a
CUDA machine (install with `uv sync --extra builder`). The full guide (methods, setup,
forwarding, troubleshooting) is still being written; this page starts with the knobs.

## Methods

- `accurate` (default): picks the nearest shipped preset by ECAPA speaker similarity, then
  optimises `style_ttl` with Adam against that similarity for up to 3000 steps, and
  finally matches the reference speaking rate by inverting `style_dp`. Measured on an
  RTX 4050 Laptop GPU (6 GB): loading ~30 s, preset scan ~12 s, 1.92 s per step, duration
  ~4.5 min, peak VRAM 2.4 GB, so a full 3000-step build takes about 100 min (it ends
  sooner if the loss reaches 0.015). The job timeout is 150 min. The ECAPA model
  (`speechbrain/spkrec-ecapa-voxceleb`) is downloaded on first use into
  `<Hugging Face hub cache>/supertonic-ecapa` (for example
  `~/.cache/huggingface/hub/supertonic-ecapa`; `HF_HUB_CACHE` / `HF_HOME` move it).
- `fast`: supertonic.embed's WavLM-statistics inversion (minutes, lower similarity).

## Build report

Every build stores a report in the voice's `build` metadata: `method`, `preset_start`
(the nearest shipped preset), `preset_distance` (that preset's loss in the scan), `loss`
(the best loss reached), `steps` (`accurate`: steps run; `fast`: the step that reached the
best loss), `duration_status`, `rate_ref`
and `rate_final` (syllable rate of the reference and of the result), and `stopped_early`.
`accurate` adds `similarity` (= 1 - loss, ECAPA cosine similarity) and `best_step` (the
step that reached the best loss; 0 means the start preset was kept). For `accurate` the
scan measures every preset on the first training sentence while the descent rotates
through all sixteen, so `loss` and `preset_distance` come from different sentences.

## Debugging knobs

| Variable | Default | Effect |
|---|---|---|
| `SUPERTONIC_BUILDER_ACCURATE_STEPS` | unset (3000) | Caps the `accurate` descent at this many steps, for quick test builds. A positive integer; anything else fails the build. Read by the builder worker process. |
