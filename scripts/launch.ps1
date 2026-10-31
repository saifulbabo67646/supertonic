# Desktop start for Windows, used by "Start Supertonic.bat".
#
# Makes sure uv is installed (installing it with Astral's official installer if not),
# installs the dependencies (with the voice builder extra when an NVIDIA GPU is present),
# then runs `supertonic-server launch`, which picks a port, starts the server and opens the
# Studio in the browser. Arguments are passed on (for example --no-open, --port 8790).
# Runs on Windows PowerShell 5.1 and PowerShell 7.
#
# Set SUPERTONIC_SKIP_BUILDER=1 to never install the voice builder extra.
$ErrorActionPreference = 'Continue'
Set-Location (Split-Path -Parent $PSScriptRoot)
$env:PYTHONUTF8 = '1'  # the console code page (cp1252) cannot print every log line

function Say([string]$Message = '') { Write-Host $Message }

function Fail([string]$Message) {
    Say ''
    Write-Host "Supertonic could not start: $Message" -ForegroundColor Red
    Say 'For help, see docs\troubleshooting.md in the Supertonic folder.'
    exit 1
}

function Test-Uv { [bool](Get-Command uv -ErrorAction SilentlyContinue) }

Say '== Supertonic'
Say ''

# 1. uv, the tool that installs Python and Supertonic's dependencies.
$uvBin = Join-Path $env:USERPROFILE '.local\bin'
if (-not (Test-Uv) -and (Test-Path (Join-Path $uvBin 'uv.exe'))) { $env:Path = "$uvBin;$env:Path" }
if (-not (Test-Uv)) {
    Say 'Supertonic needs a small free tool called uv (from Astral) to install everything else.'
    Say 'Installing it now. This happens only once.'
    Say ''
    powershell -NoProfile -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
    if ($LASTEXITCODE -ne 0) { Fail 'installing uv failed. Check your internet connection and try again.' }
    $env:Path = "$uvBin;$env:Path"
    if (-not (Test-Uv)) { Fail 'uv was installed but cannot be found. Close this window and start Supertonic again.' }
    Say ''
}

# 2. Dependencies. With an NVIDIA GPU, also the voice builder (PyTorch with CUDA, ~3 GB).
$wantBuilder = $false
if ($env:SUPERTONIC_SKIP_BUILDER -ne '1' -and (Get-Command nvidia-smi -ErrorAction SilentlyContinue)) {
    nvidia-smi *> $null
    $wantBuilder = ($LASTEXITCODE -eq 0)
}

if ($wantBuilder) {
    Say 'Found an NVIDIA graphics card, so Supertonic also installs the voice builder.'
    Say 'The first time this downloads about 3 GB and can take a while.'
    uv sync --extra builder
    if ($LASTEXITCODE -ne 0) {
        Say ''
        Say 'Note: the voice builder could not be installed (see the messages above).'
        Say 'Supertonic still works; only building new voices on this computer is unavailable.'
        Say ''
        uv sync
        if ($LASTEXITCODE -ne 0) { Fail "installing Supertonic's dependencies failed. Check your internet connection and try again." }
    }
} else {
    Say 'Installing Supertonic (the first time this takes a minute or two).'
    uv sync
    if ($LASTEXITCODE -ne 0) { Fail "installing Supertonic's dependencies failed. Check your internet connection and try again." }
}
Say ''

# 3. Start the server and open the Studio. --no-sync keeps the extras installed above.
uv run --no-sync supertonic-server launch @args
exit $LASTEXITCODE
