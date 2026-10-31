# Set up with a coding agent

If you use a coding agent (Claude Code, Codex, Cursor, Gemini CLI, GitHub Copilot's agent
or similar), it can install and start Supertonic for you. Copy the prompt below into the
agent and send it. You do not need to download anything first: the prompt tells the agent
where to get Supertonic.

The agent follows [AGENTS.md](../AGENTS.md) in the repository, which has the exact commands
for macOS, Windows and Linux, how to check that everything works, and how to stop the
server again.

## The prompt

```text
Set up Supertonic Server (a free, self-hosted text-to-speech server) on this computer.

1. If the current folder is not already the Supertonic repository, clone
   https://github.com/saifulbabo67646/supertonic.git into a folder named "supertonic" in my
   home folder (unless I named another place) and work inside it. If git is not installed,
   download and unzip https://github.com/saifulbabo67646/supertonic/archive/refs/heads/main.zip
   instead.
2. Read AGENTS.md in the repository and follow it step by step. It is the source of truth:
   if anything here disagrees with it, follow AGENTS.md.
3. Done means: the server runs in the background, `uv run supertonic-server check` prints
   PASS, and the Studio is open in my browser.

Rules:
- You may install uv. Ask me before installing anything else system-wide.
- Keep the server on 127.0.0.1. Never make it reachable from the network or the internet
  without an API key, and only if I ask for it.
- If a Supertonic server is already running, reuse it instead of starting another one.

When you are done, tell me: the Studio URL, where the log file is, the exact command to
stop the server, and anything that went wrong or that I need to do.
```

## Variations

Add one of these to the end of the prompt.

**Also build voices on this computer** (Windows or Linux with an NVIDIA graphics card):

```text
This computer has an NVIDIA graphics card. Also set up the voice builder as in section 7 of
AGENTS.md (ask me before the ~3 GB download), and confirm that
http://127.0.0.1:8787/v1/health shows "builder":"local".
```

**Connect this computer to a GPU computer that builds voices** (for example a Mac and a
Windows PC with an NVIDIA card that already runs Supertonic with the builder):

```text
My other computer, reachable with `ssh <gpu-machine>`, runs Supertonic with the voice
builder on port 8787. Forward voice builds there as in section 7 of AGENTS.md, over an SSH
tunnel unless I say otherwise. Keep the tunnel command separate and tell me how to start it
again later. Confirm that this server's /v1/health shows "builder":"remote".
```

Replace `<gpu-machine>` with the SSH name or address of that computer.

**Use Supertonic as an MCP server in Claude Code**:

```text
Also register Supertonic as an MCP server for Claude Code (user scope) as in section 8 of
AGENTS.md, and confirm `claude mcp get supertonic` shows it as connected.
```

**Replace ElevenLabs or OpenAI text-to-speech in my app**:

```text
Then switch the text-to-speech in my app at <path to the app> to this Supertonic server
instead of <ElevenLabs / OpenAI / ...>. Follow section 8 of AGENTS.md and
docs/integrations.md. Pick the closest built-in voice for each voice the app uses
(docs/voices.md) and list your choices. Keep the old provider selectable by a setting if
that is simple. Run the app's tests and show me the diff before committing anything.
```

## What the agent will do

Roughly: install uv if needed, run `uv sync --inexact`, start `uv run supertonic-server serve` in the
background with a log file, wait for `GET /v1/health`, run the smoke test (a short speech
file and word timestamps), open <http://127.0.0.1:8787/> and report back. The first start
downloads about 750 MB (the dependencies and the voice model), so it can take a few
minutes.

To stop the server later, ask the agent, or use the stop command it gave you
([AGENTS.md, step 6](../AGENTS.md#6-stop-the-server)).

If something goes wrong, the agent should find the fix in AGENTS.md. If not, see
[troubleshooting.md](troubleshooting.md) or open an issue with the agent's report (remove
any API keys first).
