# Set up this Windows machine as a Supertonic voice builder (NVIDIA GPU + CUDA required).
#
# Installs the builder extra, checks that the worker sees CUDA and both build methods,
# downloads the models a build needs, and says how to start. For a builder that other
# computers reach over a LAN it also prints the .env lines (nothing to set otherwise).
# Runs on Windows PowerShell 5.1 and PowerShell 7.
#
#   powershell -ExecutionPolicy Bypass -File scripts\setup-builder.ps1 [-Port 8787] [-OpenFirewall]
#
# -OpenFirewall adds an inbound rule for the port on Private networks (run as Administrator).
# Without it the rule command is only printed.
param(
    [int]$Port = 8787,
    [switch]$OpenFirewall
)
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path -Parent $PSScriptRoot)
$env:PYTHONUTF8 = '1'  # the console code page (cp1252) cannot print every model log line

function Fail([string]$Message) {
    Write-Host "error: $Message" -ForegroundColor Red
    exit 1
}

Write-Host '== Installing the builder extra (PyTorch with CUDA, ~3 GB on first run)'
uv sync --extra builder
if ($LASTEXITCODE -ne 0) { Fail 'uv sync --extra builder failed' }

Write-Host '== Checking the build worker'
$probeLine = uv run python -m supertonic_server.builder.worker --self-test | Select-Object -Last 1
if (-not $probeLine) { Fail 'the worker printed nothing; see the messages above' }
$probe = $probeLine | ConvertFrom-Json
if ($probe.type -eq 'error') { Fail "$($probe.code): $($probe.message)" }
if (-not $probe.cuda) {
    Fail "PyTorch $($probe.torch) does not see a CUDA GPU (check the NVIDIA driver with nvidia-smi)"
}
foreach ($method in 'accurate', 'fast') {
    if ($probe.methods -notcontains $method) {
        Fail "the '$method' method is unavailable (its dependencies do not import)"
    }
}
Write-Host ("   torch {0}, {1}, {2} MB VRAM, methods: {3}" -f `
    $probe.torch, $probe.device, $probe.vram_mb, ($probe.methods -join ', '))

Write-Host '== Downloading models (Supertonic 3, WavLM-Large, ECAPA; ~2 GB on first run)'
uv run python -m supertonic_server.builder.extract.prefetch
if ($LASTEXITCODE -ne 0) { Fail 'a model download failed; see the error above' }

# A random key for this builder (URL-safe, 32 bytes).
$bytes = New-Object byte[] 32
[System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
$key = [Convert]::ToBase64String($bytes).TrimEnd('=').Replace('+', '-').Replace('/', '_')

# The LAN address: the IPv4 address of the interface that has a default gateway.
$ip = Get-NetIPConfiguration |
    Where-Object { $_.IPv4DefaultGateway -and $_.NetAdapter.Status -eq 'Up' } |
    ForEach-Object { $_.IPv4Address.IPAddress } |
    Select-Object -First 1
if (-not $ip) { $ip = '<this-machine-lan-ip>' }

$rule = "New-NetFirewallRule -DisplayName `"Supertonic`" -Direction Inbound -Protocol TCP " +
    "-LocalPort $Port -Action Allow -Profile Private"

Write-Host ''
Write-Host '== Done. The voice builder is installed on this computer.'
Write-Host ''
Write-Host '   Start the server again (scripts\serve.ps1, or as in AGENTS.md step 4).'
Write-Host '   GET /v1/health then shows "builder":"local". Nothing else needs to change here.'
Write-Host ''
Write-Host '== Only if another computer should send its voice builds here:'
Write-Host ''
Write-Host '   Over an SSH tunnel (recommended, nothing listens on the network): leave this'
Write-Host '   computer as it is; see docs/builder.md, "Forwarding builds > Over an SSH tunnel".'
Write-Host ''
Write-Host '   Over a trusted LAN instead, put these lines in .env on THIS computer:'
Write-Host ''
Write-Host '      SUPERTONIC_HOST=0.0.0.0'
Write-Host "      SUPERTONIC_PORT=$Port"
Write-Host "      SUPERTONIC_API_KEY=$key"
Write-Host ''
Write-Host '   and these on the computer that forwards builds here:'
Write-Host ''
Write-Host "      SUPERTONIC_BUILDER_URL=http://${ip}:$Port"
Write-Host "      SUPERTONIC_BUILDER_API_KEY=$key"
Write-Host ''
if ($OpenFirewall) {
    Write-Host "== Opening TCP $Port for Private networks"
    Invoke-Expression $rule
} else {
    Write-Host '   The LAN way also needs an inbound firewall rule. As Administrator, run:'
    Write-Host ''
    Write-Host "      $rule"
    Write-Host ''
    Write-Host '   (or re-run this script with -OpenFirewall)'
}
