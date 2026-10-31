# Built-in voices

Supertonic ships ten voices. Each has a short id (`F1` to `F5` for the female voices, `M1` to
`M5` for the male ones) and a name. Use whichever you like: `"voice": "Mia"`, `"voice": "mia"`
and `"voice": "F1"` all pick the same voice, in the REST API, the OpenAI-compatible endpoint,
the realtime WebSocket, the MCP tools and the web UI. Ids never change, so code that already
says `F1` keeps working. Responses always name the voice by its id.

| Id | Name | Description | Median pitch (Hz) | Pace (syllables/s) |
|---|---|---|---:|---:|
| F1 | Mia | Higher-pitched female voice with an unhurried pace; suits narration and explainers. | 179 | 3.59 |
| F2 | Nora | Higher-pitched female voice with a moderate pace; suits assistants and product tours. | 190 | 3.84 |
| F3 | Lena | Lower-pitched female voice with an unhurried pace; suits audiobooks and calm reading. | 162 | 3.48 |
| F4 | Sofia | Higher-pitched female voice with a brisk pace; suits ads, promos and short social clips. | 192 | 4.18 |
| F5 | Yuna | Lower-pitched female voice with a moderate pace; suits e-learning and announcements. | 161 | 3.72 |
| M1 | Hugo | Higher-pitched male voice with an unhurried pace; suits tutorials and walkthroughs. | 125 | 3.59 |
| M2 | Diego | Lower-pitched male voice with a moderate pace; suits documentaries and trailers. | 90 | 3.68 |
| M3 | Ravi | Lower-pitched male voice with a brisk pace; suits news reads and quick updates. | 96 | 4.29 |
| M4 | Felix | Higher-pitched male voice with a moderate pace; suits voice agents and support calls. | 114 | 3.85 |
| M5 | Omar | Lower-pitched male voice with an unhurried pace; suits storytelling and long-form narration. | 88 | 3.60 |

The best way to choose is to listen: the Voices page of the web UI plays a sample of each
voice in any language, and so does `GET /v1/voices/{id or name}/preview?language=en`.

## How the descriptions were made

Pitch and pace are measured, not guessed. `scripts/describe_presets.py` speaks the same two
sentences with every voice at speed 1.0 (8 steps):

> The quick brown fox jumps over the lazy dog near the riverbank. Please call me back when
> you have a moment to talk about the plan.

- **Pitch** is the median fundamental frequency over voiced frames, found with a plain
  autocorrelation tracker. "Higher" and "lower" compare a voice with the other voices of
  the same gender; the female voices fall into two clear groups (about 160 Hz and
  180-190 Hz), as do the male ones (about 90-96 Hz and 115-125 Hz).
- **Pace** is the syllables of the two sentences (32) divided by the length of the speech.
  It is compared across all ten voices: unhurried below 3.65, brisk above 4.0, moderate in
  between.
- The **suggested use** is only a suggestion; nothing about it was measured.

Synthesis varies a little from run to run, so pitch moves by a few Hz between runs (each
figure is the median of three); pace is stable. The figures describe English speech at the
default settings; other languages and speeds will differ. Re-run with
`uv run python scripts/describe_presets.py`.

## Names and custom voices

Built-in names are reserved: a custom voice cannot be imported, built or renamed to a
built-in voice's name or id (any capitalisation). The server answers
`409 voice_name_taken`. When a voice is looked up, the order is: exact id, id in any
capitalisation, built-in name, then custom voice name. A custom voice saved before names
existed that is called, say, "Mia" keeps working by its own id; the name "Mia" now means
`F1`.

Names and descriptions live in one place, `src/supertonic_server/voices/presets.py`.
