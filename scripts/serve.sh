#!/usr/bin/env bash
# Install dependencies and start the Supertonic server. Settings come from .env / SUPERTONIC_*.
set -euo pipefail
cd "$(dirname "$0")/.."
uv sync
exec uv run supertonic-server serve "$@"
