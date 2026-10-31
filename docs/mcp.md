# MCP server (Claude Code and other agents)

`supertonic-mcp` is a stdio MCP server that talks to a running Supertonic server and saves
audio files on the machine it runs on. Tools: `list_languages`, `list_voices`, `speak`
(optionally with word timestamps) and `preview_voice` (a voice is an id like `F1` or a name
like `Mia`), plus voice building:
`build_voice` (reference audio paths, name, `source_note`, `consent`, `method` `accurate` or
`fast`), `get_job`, `list_jobs` and `finish_job`. Once a build succeeded, `get_job` also
returns the new voice's `build` report; `pitch_match: false` there means the voice sounds
clearly higher or lower than the recording ([builder.md](builder.md#the-pitch-check)).

Claude Code:

```bash
claude mcp add supertonic --scope user \
  --env SUPERTONIC_BASE_URL=http://127.0.0.1:8787 \
  --env SUPERTONIC_API_KEY=your-key-if-set \
  -- uv --directory /path/to/supertonic run supertonic-mcp
```

Use the absolute path of your Supertonic folder. `--scope user` makes it available in every
project (leave it out for the current project only). `claude mcp get supertonic` should
then show `Status: ✔ Connected`. The Studio's **Connect** page shows the same command with this
server's address.

Any other MCP client (generic JSON config):

```json
{
  "mcpServers": {
    "supertonic": {
      "command": "uv",
      "args": ["--directory", "/path/to/supertonic", "run", "supertonic-mcp"],
      "env": {
        "SUPERTONIC_BASE_URL": "http://127.0.0.1:8787",
        "SUPERTONIC_API_KEY": "your-key-if-set"
      }
    }
  }
}
```

Omit `SUPERTONIC_API_KEY` when the server has none. Files go to `SUPERTONIC_MCP_OUTPUT_DIR`
(default `./supertonic-output`, which with `uv --directory` is inside the Supertonic folder)
unless `speak` is given an `output_path`. The Supertonic server must be running; the MCP
process only forwards to it.
