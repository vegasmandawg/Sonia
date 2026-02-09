<#
.SYNOPSIS
Verify that the Sonia stack is bootable

.DESCRIPTION
Checks that all required files exist and are properly configured.
Does NOT start services - use start-sonia-stack.ps1 for that.

.PARAMETER Root
Sonia root directory. Defaults to S:\
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory=$false)]
    [string]$Root = "S:\"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# Helper
function Test-File {
    param([string]$Path, [string]$Description)
    if (Test-Path -LiteralPath $Path) {
        Write-Host "[✓] $Description" -ForegroundColor Green
        return $true
    } else {
        Write-Host "[✗] $Description - NOT FOUND: $Path" -ForegroundColor Red
        return $false
    }
}

function Test-Directory {
    param([string]$Path, [string]$Description)
    if (Test-Path -LiteralPath $Path -PathType Container) {
        Write-Host "[✓] $Description" -ForegroundColor Green
        return $true
    } else {
        Write-Host "[✗] $Description - NOT FOUND: $Path" -ForegroundColor Red
        return $false
    }
}

# ─────────────────────────────────────────────────────────────────────────────
# Header
# ─────────────────────────────────────────────────────────────────────────────

Write-Host ""
Write-Host "╔═════════════════════════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "║    SONIA BOOTABLE STACK VERIFICATION                   ║" -ForegroundColor Cyan
Write-Host "╚═════════════════════════════════════════════════════════╝" -ForegroundColor Cyan
Write-Host ""

if (-not $Root.EndsWith("\")) { $Root = "$Root\" }

Write-Host "Root: $Root" -ForegroundColor Gray
Write-Host ""

# ─────────────────────────────────────────────────────────────────────────────
# Verification
# ─────────────────────────────────────────────────────────────────────────────

$allGood = $true

Write-Host "Checking Library & Utilities..." -ForegroundColor Cyan
Write-Host "──────────────────────────────────────────────────────────"
$allGood = (Test-File (Join-Path $Root "scripts\lib\sonia-stack.ps1") "Library functions") -and $allGood
Write-Host ""

Write-Host "Checking Startup Scripts..." -ForegroundColor Cyan
Write-Host "──────────────────────────────────────────────────────────"
$allGood = (Test-File (Join-Path $Root "scripts\ops\run-api-gateway.ps1") "API Gateway launcher") -and $allGood
$allGood = (Test-File (Join-Path $Root "scripts\ops\run-model-router.ps1") "Model Router launcher") -and $allGood
$allGood = (Test-File (Join-Path $Root "scripts\ops\run-memory-engine.ps1") "Memory Engine launcher") -and $allGood
$allGood = (Test-File (Join-Path $Root "scripts\ops\run-pipecat.ps1") "Pipecat launcher") -and $allGood
$allGood = (Test-File (Join-Path $Root "scripts\ops\run-openclaw.ps1") "OpenClaw launcher") -and $allGood
$allGood = (Test-File (Join-Path $Root "scripts\ops\run-eva-os.ps1") "EVA-OS launcher") -and $allGood
Write-Host ""

Write-Host "Checking Main Stack Scripts..." -ForegroundColor Cyan
Write-Host "──────────────────────────────────────────────────────────"
$allGood = (Test-File (Join-Path $Root "start-sonia-stack.ps1") "Stack startup script") -and $allGood
$allGood = (Test-File (Join-Path $Root "stop-sonia-stack.ps1") "Stack shutdown script") -and $allGood
Write-Host ""

Write-Host "Checking Service Entry Points..." -ForegroundColor Cyan
Write-Host "──────────────────────────────────────────────────────────"
$allGood = (Test-File (Join-Path $Root "services\api-gateway\main.py") "API Gateway main.py") -and $allGood
$allGood = (Test-File (Join-Path $Root "services\model-router\main.py") "Model Router main.py") -and $allGood
$allGood = (Test-File (Join-Path $Root "services\memory-engine\main.py") "Memory Engine main.py") -and $allGood
$allGood = (Test-File (Join-Path $Root "services\pipecat\main.py") "Pipecat main.py") -and $allGood
$allGood = (Test-File (Join-Path $Root "services\openclaw\main.py") "OpenClaw main.py") -and $allGood
$allGood = (Test-File (Join-Path $Root "services\eva-os\main.py") "EVA-OS main.py") -and $allGood
Write-Host ""

Write-Host "Checking Directories..." -ForegroundColor Cyan
Write-Host "──────────────────────────────────────────────────────────"
$allGood = (Test-Directory (Join-Path $Root "state\pids") "PID directory") -and $allGood
$allGood = (Test-Directory (Join-Path $Root "logs\services") "Logs directory") -and $allGood
$allGood = (Test-Directory (Join-Path $Root "services\api-gateway") "API Gateway service") -and $allGood
$allGood = (Test-Directory (Join-Path $Root "services\model-router") "Model Router service") -and $allGood
$allGood = (Test-Directory (Join-Path $Root "services\memory-engine") "Memory Engine service") -and $allGood
$allGood = (Test-Directory (Join-Path $Root "services\pipecat") "Pipecat service") -and $allGood
$allGood = (Test-Directory (Join-Path $Root "services\openclaw") "OpenClaw service") -and $allGood
$allGood = (Test-Directory (Join-Path $Root "services\eva-os") "EVA-OS service") -and $allGood
Write-Host ""

Write-Host "Checking Configuration Files..." -ForegroundColor Cyan
Write-Host "──────────────────────────────────────────────────────────"
$allGood = (Test-File (Join-Path $Root ".env.example") "Environment template") -and $allGood
Write-Host ""

Write-Host "Checking Documentation..." -ForegroundColor Cyan
Write-Host "──────────────────────────────────────────────────────────"
$allGood = (Test-File (Join-Path $Root "BOOTSTRAP.md") "Bootstrap guide") -and $allGood
$allGood = (Test-File (Join-Path $Root "BOOTSTRAP_CHECKLIST.md") "Bootstrap checklist") -and $allGood
$allGood = (Test-File (Join-Path $Root "BOOTABLE_STACK_SUMMARY.md") "Bootable stack summary") -and $allGood
Write-Host ""

# ─────────────────────────────────────────────────────────────────────────────
# Python Check
# ─────────────────────────────────────────────────────────────────────────────

Write-Host "Checking Python Environment..." -ForegroundColor Cyan
Write-Host "──────────────────────────────────────────────────────────"

$pythonExe = $null

# Check local environment
if (Test-Path (Join-Path $Root "envs\sonia-core\python.exe")) {
    $pythonExe = Join-Path $Root "envs\sonia-core\python.exe"
    Write-Host "[✓] Found Python in sonia-core environment" -ForegroundColor Green
}
# Check PATH
elseif ($null -ne (Get-Command python -ErrorAction SilentlyContinue)) {
    $pythonExe = (Get-Command python).Source
    Write-Host "[✓] Found Python in PATH: $pythonExe" -ForegroundColor Green
}
else {
    Write-Host "[✗] Python not found - install Python 3.11+ or create sonia-core environment" -ForegroundColor Red
    $allGood = $false
}

if ($pythonExe) {
    try {
        $version = & $pythonExe --version
        Write-Host "[✓] $version" -ForegroundColor Green
    }
    catch {
        Write-Host "[✗] Failed to get Python version: $_" -ForegroundColor Red
        $allGood = $false
    }
}

Write-Host ""

# ─────────────────────────────────────────────────────────────────────────────
# Port Check
# ─────────────────────────────────────────────────────────────────────────────

Write-Host "Checking Required Ports..." -ForegroundColor Cyan
Write-Host "──────────────────────────────────────────────────────────"

$ports = @(7000, 7010, 7020, 7030, 7040, 7050)
foreach ($port in $ports) {
    try {
        $listener = New-Object System.Net.Sockets.TcpListener([System.Net.IPAddress]::Loopback, $port)
        $listener.Start()
        $listener.Stop()
        Write-Host "[✓] Port $port available" -ForegroundColor Green
    }
    catch {
        Write-Host "[✗] Port $port IN USE" -ForegroundColor Red
        $allGood = $false
    }
}

Write-Host ""

# ─────────────────────────────────────────────────────────────────────────────
# Summary
# ─────────────────────────────────────────────────────────────────────────────

Write-Host "╔═════════════════════════════════════════════════════════╗" -ForegroundColor Cyan
if ($allGood) {
    Write-Host "║           ✓ STACK IS BOOTABLE                           ║" -ForegroundColor Cyan
    Write-Host "╚═════════════════════════════════════════════════════════╝" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "All requirements met! Ready to start." -ForegroundColor Green
    Write-Host ""
    Write-Host "Next steps:" -ForegroundColor Cyan
    Write-Host "  1. .\start-sonia-stack.ps1" -ForegroundColor Gray
    Write-Host "  2. iwr http://127.0.0.1:7000/healthz" -ForegroundColor Gray
    Write-Host "  3. .\stop-sonia-stack.ps1" -ForegroundColor Gray
    Write-Host ""
    exit 0
}
else {
    Write-Host "║           ✗ ISSUES FOUND                               ║" -ForegroundColor Red
    Write-Host "╚═════════════════════════════════════════════════════════╝" -ForegroundColor Red
    Write-Host ""
    Write-Host "Fix the issues above and try again." -ForegroundColor Red
    Write-Host ""
    exit 1
}
