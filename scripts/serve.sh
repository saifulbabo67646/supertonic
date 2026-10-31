#!/usr/bin/env bash
# Install dependencies and start the Supertonic server. Settings come from .env / SUPERTONIC_*.
set -euo pipefail
cd "$(dirname "$0")/.."
# --inexact keeps the voice builder extra if it was installed (a plain sync removes it).
uv sync --inexact
exec uv run supertonic-server serve "$@"
