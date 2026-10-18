#!/usr/bin/env bash
# Set up this Linux machine as a Supertonic voice builder (NVIDIA GPU + CUDA required).
#
# Installs the builder extra, checks that the worker sees CUDA and both build methods,
# downloads the models a build needs, and prints the .env lines for this machine and for
# the machine that forwards builds here.
#
#   scripts/setup-builder.sh [port]        (default port 8787)
set -euo pipefail
cd "$(dirname "$0")/.."
port="${1:-8787}"
export PYTHONUTF8=1

fail() { echo "error: $*" >&2; exit 1; }

if [ "$(uname -s)" = "Darwin" ]; then
  cat >&2 <<'MSG'
Voice building needs an NVIDIA GPU with CUDA, which macOS does not have.
Run the server here as usual and forward builds to a Linux or Windows machine with a GPU:
set SUPERTONIC_BUILDER_URL (and SUPERTONIC_BUILDER_API_KEY) in this machine's .env.
See docs/builder.md, "Forwarding builds".
MSG
  exit 1
fi

echo "== Installing the builder extra (PyTorch with CUDA, ~3 GB on first run)"
uv sync --extra builder || fail "uv sync --extra builder failed"

echo "== Checking the build worker"
probe="$( (uv run python -m supertonic_server.builder.worker --self-test || true) | tail -n 1)"
[ -n "$probe" ] || fail "the worker printed nothing; see the messages above"
summary="$(printf '%s' "$probe" | uv run python -c '
import json, sys
p = json.loads(sys.stdin.read())
if p.get("type") == "error":
    sys.exit("{}: {}".format(p.get("code"), p.get("message")))
if not p.get("cuda"):
    sys.exit("PyTorch {} does not see a CUDA GPU (check nvidia-smi)".format(p.get("torch")))
methods = p.get("methods", [])
missing = [m for m in ("accurate", "fast") if m not in methods]
if missing:
    sys.exit("unavailable (dependencies do not import): " + ", ".join(missing))
info = (p.get("torch"), p.get("device"), p.get("vram_mb"), ", ".join(methods))
print("torch {}, {}, {} MB VRAM, methods: {}".format(*info))
')" || fail "the worker self-test did not pass (see above)"
echo "   $summary"

echo "== Downloading models (Supertonic 3, WavLM-Large, ECAPA; ~2 GB on first run)"
uv run python -m supertonic_server.builder.extract.prefetch || fail "a model download failed"

key="$(uv run python -c 'import secrets; print(secrets.token_urlsafe(32))')"
ip="$( (ip -4 route get 1.1.1.1 2>/dev/null | awk '{for (i = 1; i < NF; i++) if ($i == "src") print $(i + 1)}') || true)"
[ -n "$ip" ] || ip="$(hostname -I 2>/dev/null | awk '{print $1}')"
[ -n "$ip" ] || ip="<this-machine-lan-ip>"

cat <<MSG

== Done. Put these lines in .env on THIS machine (the builder):

   SUPERTONIC_HOST=0.0.0.0
   SUPERTONIC_PORT=$port
   SUPERTONIC_API_KEY=$key

== ...and these on the machine that forwards builds here:

   SUPERTONIC_BUILDER_URL=http://$ip:$port
   SUPERTONIC_BUILDER_API_KEY=$key

   Then start the builder with scripts/serve.sh.
   If a firewall is active, allow TCP $port from your LAN only, e.g.:
     sudo ufw allow from 192.168.0.0/16 to any port $port proto tcp
   No trusted LAN? Keep SUPERTONIC_HOST=127.0.0.1 here and use an SSH tunnel instead
   (see docs/builder.md, "Forwarding builds > Over an SSH tunnel").
MSG
