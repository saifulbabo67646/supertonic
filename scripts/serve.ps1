# Install dependencies and start the Supertonic server. Settings come from .env / SUPERTONIC_*.
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path -Parent $PSScriptRoot)
# --inexact keeps the voice builder extra if it was installed (a plain sync removes it).
uv sync --inexact
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
uv run supertonic-server serve @args
exit $LASTEXITCODE
