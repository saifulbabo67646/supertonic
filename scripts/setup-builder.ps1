# Set up this Windows machine as a Supertonic voice builder (NVIDIA GPU + CUDA required).
#
# Installs the builder extra, checks that the worker sees CUDA and both build methods,
# downloads the models a build needs, and prints the .env lines for this machine and for
# the machine that forwards builds here. Runs on Windows PowerShell 5.1 and PowerShell 7.
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
Write-Host '== Done. Put these lines in .env on THIS machine (the builder):'
Write-Host ''
Write-Host '   SUPERTONIC_HOST=0.0.0.0'
Write-Host "   SUPERTONIC_PORT=$Port"
Write-Host "   SUPERTONIC_API_KEY=$key"
Write-Host ''
Write-Host '== ...and these on the machine that forwards builds here:'
Write-Host ''
Write-Host "   SUPERTONIC_BUILDER_URL=http://${ip}:$Port"
Write-Host "   SUPERTONIC_BUILDER_API_KEY=$key"
Write-Host ''
Write-Host '   Then start the builder with scripts\serve.ps1.'
Write-Host '   No trusted LAN? Keep SUPERTONIC_HOST=127.0.0.1 here and use an SSH tunnel instead'
Write-Host '   (see docs/builder.md, "Forwarding builds > Over an SSH tunnel").'
Write-Host ''
if ($OpenFirewall) {
    Write-Host "== Opening TCP $Port for Private networks"
    Invoke-Expression $rule
} else {
    Write-Host '== Other machines on the LAN need an inbound firewall rule. As Administrator, run:'
    Write-Host ''
    Write-Host "   $rule"
    Write-Host ''
    Write-Host '   (or re-run this script with -OpenFirewall)'
}
