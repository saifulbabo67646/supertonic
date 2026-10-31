# Documentation

Start with the [project README](../README.md) for what Supertonic Server is and how to run
it, or with [Getting started](getting-started.md) if you do not use a terminal. These pages
go deeper.

| Page | What it covers |
|---|---|
| [Getting started](getting-started.md) | The beginner's guide: download, double-click, a tour of the Studio, making your own voice, updating and uninstalling. No terminal needed. |
| [Set up with a coding agent](agent-setup.md) | One prompt to paste into Claude Code, Codex, Cursor or another coding agent, plus variations. The agent follows [AGENTS.md](../AGENTS.md). |
| [Troubleshooting](troubleshooting.md) | Starting with the double-click launchers: first start, macOS and Windows warnings, ports, the voice builder install, where data lives and how to reset. |
| [API reference](api.md) | Every HTTP endpoint and the realtime WebSocket: requests, responses, limits and error codes. |
| [Built-in voices](voices.md) | The ten built-in voices, their names, what they sound like and how that was measured. |
| [Voice builder](builder.md) | Building a voice from your own recordings on an NVIDIA GPU, forwarding builds from another machine, and troubleshooting. |
| [Integration notes](integrations.md) | Using the server from OpenAI-style apps, a live voice agent or a video narration pipeline, and moving from a hosted voice service. |
| [MCP server](mcp.md) | Letting Claude Code and other AI assistants speak, audition and build voices. |
| [Configuration](configuration.md) | Every setting (`SUPERTONIC_*` environment variables and `.env`). |
| [Remote access and security](remote-access.md) | API keys, using the server from other computers, Cloudflare Tunnel, and why a keyless server refuses web pages and proxies. |
| [Latency benchmarks](benchmarks.md) | How fast speech starts on CPU, alone and under load, and how it was measured. |
| [Voice builder benchmarks](benchmarks-builder.md) | How long voice builds take and how close they sound, measured on a laptop GPU. |

Project policies live at the top of the repository: [contributing](../CONTRIBUTING.md),
[code of conduct](../CODE_OF_CONDUCT.md), [security](../SECURITY.md),
[changelog](../CHANGELOG.md) and [third-party notices](../THIRD_PARTY_NOTICES.md).
