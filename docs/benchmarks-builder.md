# Voice builder benchmarks

How long a voice build takes, how much GPU memory it needs and how close the result gets.
See [builder.md](builder.md) for what the methods do.

**Machine:** NVIDIA GeForce RTX 4050 Laptop GPU (6 GB), Windows 11, driver 551 (CUDA 12.4),
PyTorch 2.9.1+cu126. VRAM figures are `nvidia-smi` totals and include about 0.7 GB used
by the desktop. Reference recordings: the two sample references that ship with Supertonic 3
(`luna`, female, and `watson`, male).

## End-to-end run (2026-10-19)

A Mac (no GPU) forwarded every build to the Windows builder through an SSH tunnel
(`SUPERTONIC_BUILDER_URL=http://127.0.0.1:8788`), and imported each finished voice into
its own library (`build.builder: "remote:127.0.0.1:8788"`); the builder kept its own copy
(`builder: "local"`). Each path was driven through a different interface.

| Voice | Method | Driven from | Outcome | Steps (best) | Loss | Similarity | Job wall time | Peak VRAM |
|---|---|---|---|---|---|---|---|---|
| luna | `fast` | MCP (`build_voice`, `get_job`) | succeeded | 349 | 0.240 (WavLM) | – | 13.4 min | 4.5 GB |
| watson | `accurate` | web UI, Cancel in the timbre stage | cancelled after 86 s, nothing imported, VRAM back to idle within 1 s | – | – | – | 1.4 min | 3.4 GB |
| luna | `accurate` | web UI, Finish now at step 312 | succeeded, `stopped_early: true` | 319 (314) | 0.195 | 0.805 | 11.1 min | 3.4 GB |
| watson | `accurate` | REST (`curl`) | succeeded, full run | 3000 (2999) | 0.032 | **0.968** | 100.4 min | 3.4 GB |

Stage timings of the full `accurate` build (watson):

| Stage | Time |
|---|---|
| Upload, checks, forwarding | under 10 s |
| Loading (Supertonic 3 to PyTorch, ECAPA) | 26 s |
| Nearest-preset scan (10 presets; nearest `F5`, see notes) | 26 s |
| Timbre optimisation, 3000 steps | 97.0 min (1.94 s per step) |
| Rhythm (`style_dp`) matching | 2.4 min (`converged`: rate 3.77 → 3.86 syllables/s) |
| Saving and import on both machines | under 10 s |

The `fast` build spent about 1 min loading and scanning, 10 min in 349 optimisation steps
(1.7 s per step, stopped by its own convergence rule) and 2.3 min matching the rhythm.

Notes:

- `accurate` keeps improving until the last step (best step 2999 of 3000); the default
  early stop (loss ≤ 0.015) was not reached. Similarity was 0.80 after about 300 steps, so
  Finish now after 10 to 20 minutes already gives a usable voice.
- The Finish now run above skipped the rhythm matching (11.1 min). Finish now has since
  been changed to end only the timbre stage: the rhythm matching still runs, which adds
  about 2.5 minutes and gives the early voice the speaker's own pace.
- The nearest preset for watson in the `accurate` (ECAPA) scan was `F5`; in the R1 spike the
  WavLM scan picked `M5`. The scan only chooses the starting point.
- `similarity` is the same ECAPA score `accurate` optimises, so it is optimistic; listening
  decides. The voices then synthesised normally on the Mac's CPU in English, Japanese and
  Korean.

## R1 spike (2026-10-18/19)

Before the builder was written, both upstream tools were run unchanged on the same laptop
(CUDA 12.4 driver, torch 2.9.1+cu126). Speaker similarity = ECAPA cosine between the
reference recording and Supertonic output (2 English sentences, 1 Japanese sentence):

| Voice | Method | en | ja | Time | Peak VRAM |
|---|---|---|---|---|---|
| luna | nearest preset (F1) | 0.31 | 0.43 | – | – |
| luna | supertonic.embed (`fast`) | 0.38 | 0.54 | 5.4 min (181 steps) | 4.4 GB |
| luna | supertonic3-voice-clone (`accurate`) | **0.90** | **0.88** | 91 min (3000 steps) | 3.4 GB |
| watson | nearest preset (M5) | 0.10 | 0.23 | – | – |
| watson | supertonic.embed (`fast`) | 0.50 | 0.71 | ≈9 min (319 steps) | 4.4 GB |

- Both repos work on Supertonic 3 unchanged (v3 ONNX input order and unit-sphere presets
  match). VRAM includes about 0.6 GB desktop use.
- Caveat: `accurate` optimises the same ECAPA measure the evaluation uses, so its number is
  optimistic.
- supertonic3-voice-clone freezes `style_dp` (speaking rhythm) at the nearest preset;
  supertonic.embed inverts it from the reference. The builder's `accurate` method adds
  supertonic.embed's rhythm inversion after the timbre optimisation.
- Windows: PowerShell 5 writes UTF-8 with a BOM, the console's cp1252 breaks non-ASCII
  output (`PYTHONUTF8=1`), torchaudio 2.9 `load` needs FFmpeg shared DLLs (the builder
  decodes with soundfile instead) and SpeechBrain's symlink fetch fails without developer
  mode (the builder copies instead).

The builder's `fast` runs took longer than the spike (13 min vs 5 to 9 min) because it also
inverts the rhythm (about 2.3 min) and its timbre stage ran more steps before converging.
