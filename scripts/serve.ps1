# Install dependencies and start the Supertonic server. Settings come from .env / SUPERTONIC_*.
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path -Parent $PSScriptRoot)
uv sync
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
uv run supertonic-server serve @args
exit $LASTEXITCODE
