#!/usr/bin/env bash
# Desktop start for macOS and Linux, used by "Start Supertonic.command" and start-supertonic.sh.
#
# Makes sure uv is installed (installing it with Astral's official installer if not),
# installs the dependencies (with the voice builder extra when an NVIDIA GPU is present on
# Linux), then runs `supertonic-server launch`, which picks a port, starts the server and
# opens the Studio in the browser. Arguments are passed on (for example --no-open, --port).
#
# Set SUPERTONIC_SKIP_BUILDER=1 to never install the voice builder extra.
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1

say() { printf '%s\n' "$*"; }

finish() {
  # Keep a double-clicked window open so the message can be read.
  if [ -t 0 ] && [ -t 1 ]; then
    say ""
    read -r -p "Press Enter to close this window. " _ || true
  fi
}

fail() {
  say ""
  say "Supertonic could not start: $*"
  say "For help, see docs/troubleshooting.md in the Supertonic folder."
  finish
  exit 1
}

say "== Supertonic"
say ""

# 1. uv, the tool that installs Python and Supertonic's dependencies.
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
if ! command -v uv >/dev/null 2>&1; then
  say "Supertonic needs a small free tool called uv (from Astral) to install everything else."
  say "Installing it now. This happens only once."
  say ""
  if command -v curl >/dev/null 2>&1; then
    curl -LsSf https://astral.sh/uv/install.sh | sh || fail "installing uv failed. Check your internet connection and try again."
  elif command -v wget >/dev/null 2>&1; then
    wget -qO- https://astral.sh/uv/install.sh | sh || fail "installing uv failed. Check your internet connection and try again."
  else
    fail "neither curl nor wget is installed, so uv cannot be downloaded. Install curl and try again."
  fi
  hash -r
  command -v uv >/dev/null 2>&1 || fail "uv was installed but cannot be found. Close this window and start Supertonic again."
  say ""
fi

# 2. Dependencies. With an NVIDIA GPU (Linux), also the voice builder (PyTorch, ~3 GB).
want_builder=0
if [ "$(uname -s)" = "Linux" ] && [ "${SUPERTONIC_SKIP_BUILDER:-0}" != "1" ] \
  && command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi >/dev/null 2>&1; then
  want_builder=1
fi

if [ "$want_builder" = "1" ]; then
  say "Found an NVIDIA graphics card, so Supertonic also installs the voice builder."
  say "The first time this downloads about 3 GB and can take a while."
  if ! uv sync --extra builder; then
    say ""
    say "Note: the voice builder could not be installed (see the messages above)."
    say "Supertonic still works; only building new voices on this computer is unavailable."
    say ""
    uv sync || fail "installing Supertonic's dependencies failed. Check your internet connection and try again."
  fi
else
  say "Installing Supertonic (the first time this takes a minute or two)."
  uv sync || fail "installing Supertonic's dependencies failed. Check your internet connection and try again."
fi
say ""

# 3. Start the server and open the Studio. --no-sync keeps the extras installed above.
uv run --no-sync supertonic-server launch "$@"
status=$?
# 130 = stopped with Ctrl+C, 129 = window closed: both are normal ways to stop.
if [ "$status" -ne 0 ] && [ "$status" -ne 130 ] && [ "$status" -ne 129 ]; then
  finish
fi
exit "$status"
