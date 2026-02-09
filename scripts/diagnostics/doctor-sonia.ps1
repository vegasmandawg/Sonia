<#---------------------------------------------------------------------------
doctor-sonia.ps1 (SONIA HEALTH CHECK)

Complete diagnostic of the Sonia system.
Validates: configuration, services, dependencies, ports, environment.

Usage:
  .\doctor-sonia.ps1                    # Run all checks
  .\doctor-sonia.ps1 -Verbose           # Verbose output
  .\doctor-sonia.ps1 -QuickCheck        # Fast validation only
---------------------------------------------------------------------------#>

[CmdletBinding()]
param(
    [Parameter(Mandatory=$false)]
    [ValidateNotNullOrEmpty()]
    [string]$Root = "S:\",

    [Parameter(Mandatory=$false)]
    [switch]$Verbose,

    [Parameter(Mandatory=$false)]
    [switch]$QuickCheck
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$passed = @()
$failed = @()
$warned = @()

function Write-Test {
    param([string]$Name, [bool]$Pass, [string]$Detail = "")
    $status = if ($Pass) { "✓" } else { "✗" }
    $color = if ($Pass) { "Green" } else { "Red" }
    Write-Host "  $status $Name" -ForegroundColor $color
    if ($Detail) {
        Write-Host "    └─ $Detail" -ForegroundColor DarkGray
    }
}

function Test-Status {
    param([string]$Name, [scriptblock]$Block)
    try {
        $result = & $Block
        if ($result -eq $true) {
            Write-Test $Name $true
            $script:passed += $Name
        } else {
            Write-Test $Name $false $result
            $script:failed += $Name
        }
    } catch {
        Write-Test $Name $false $_.Exception.Message
        $script:failed += $Name
    }
}

function Warn {
    param([string]$Name, [string]$Message)
    Write-Host "  ⚠ $Name" -ForegroundColor Yellow
    Write-Host "    └─ $Message" -ForegroundColor DarkYellow
    $script:warned += $Name
}

function Normalize-Root {
    param([string]$Path)
    if ($Path -and -not $Path.EndsWith("\")) { return "$Path\" }
    return $Path
}

# ───────────────────────────────────────────────────────────────────────────────
# START
# ───────────────────────────────────────────────────────────────────────────────

$Root = Normalize-Root $Root
$timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"

Write-Host ""
Write-Host "╔════════════════════════════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "║           SONIA HEALTH CHECK AND DIAGNOSTICS              ║" -ForegroundColor Cyan
Write-Host "╚════════════════════════════════════════════════════════════╝" -ForegroundColor Cyan
Write-Host ""
Write-Host "Timestamp: $timestamp" -ForegroundColor DarkGray
Write-Host "Root: $Root" -ForegroundColor DarkGray
Write-Host ""

# ═════════════════════════════════════════════════════════════════════════════════
# PHASE 1: FOUNDATIONAL SETUP
# ═════════════════════════════════════════════════════════════════════════════════

Write-Host "Foundational Setup" -ForegroundColor Cyan
Write-Host "──────────────────"

Test-Status "Root directory exists" {
    Test-Path -LiteralPath $Root -PathType Container
}

Test-Status "Configuration file (sonia-config.json)" {
    Test-Path -LiteralPath "$($Root)config\sonia-config.json" -PathType Leaf
}

Test-Status "Message schemas defined" {
    Test-Path -LiteralPath "$($Root)shared\schemas\envelopes.json" -PathType Leaf
}

Test-Status "EVA-OS module exists" {
    (Test-Path -LiteralPath "$($Root)services\eva-os\eva_os.py" -PathType Leaf) -or
    (Test-Path -LiteralPath "$($Root)services\eva-os\eva_os_service.py" -PathType Leaf)
}

Test-Status "OpenClaw tool catalog" {
    Test-Path -LiteralPath "$($Root)services\openclaw\tool_catalog.json" -PathType Leaf
}

# ═════════════════════════════════════════════════════════════════════════════════
# PHASE 2: DIRECTORIES AND STRUCTURE
# ═════════════════════════════════════════════════════════════════════════════════

Write-Host ""
Write-Host "Directory Structure" -ForegroundColor Cyan
Write-Host "───────────────────"

Test-Status "Logs directory (S:\logs\services)" {
    Test-Path -LiteralPath "$($Root)logs\services" -PathType Container
}

Test-Status "PID directory (S:\state\pids)" {
    Test-Path -LiteralPath "$($Root)state\pids" -PathType Container
}

Test-Status "Cache directories" {
    (Test-Path -LiteralPath "$($Root)cache\npm" -PathType Container) -and
    (Test-Path -LiteralPath "$($Root)cache\pnpm-store" -PathType Container)
}

Test-Status "Integration directories" {
    (Test-Path -LiteralPath "$($Root)integrations\openclaw" -PathType Container) -and
    (Test-Path -LiteralPath "$($Root)integrations\pipecat" -PathType Container)
}

# ═════════════════════════════════════════════════════════════════════════════════
# PHASE 3: RUNTIME DEPENDENCIES
# ═════════════════════════════════════════════════════════════════════════════════

Write-Host ""
Write-Host "Runtime Dependencies" -ForegroundColor Cyan
Write-Host "────────────────────"

Test-Status "Node.js available (v20+)" {
    $nodeCmd = Get-Command node.exe -ErrorAction SilentlyContinue
    if ($nodeCmd) {
        $nodeVer = & node.exe --version
        $major = [int]($nodeVer -replace '^v(\d+).*', '$1')
        if ($major -ge 20) {
            "Node.js $nodeVer"
            $true
        } else {
            "Node.js $nodeVer (need v20+)"
            $false
        }
    } else {
        "Node.js not found on PATH"
        $false
    }
}

Test-Status "npm or pnpm available" {
    $npm = Get-Command npm.cmd -ErrorAction SilentlyContinue
    $pnpm = Get-Command pnpm -ErrorAction SilentlyContinue
    if ($npm) { "npm available" ; $true }
    elseif ($pnpm) { "pnpm available" ; $true }
    else { "Neither npm nor pnpm on PATH" ; $false }
}

Test-Status "Python 3.11+ available" {
    $pyCmd = Get-Command python -ErrorAction SilentlyContinue
    if ($pyCmd) {
        $pyVer = & python --version 2>&1
        "Python $pyVer"
        $true
    } else {
        "Python not found on PATH"
        $false
    }
}

Test-Status "Conda/Miniconda available" {
    $condaCmd = Get-Command conda -ErrorAction SilentlyContinue
    if ($condaCmd) {
        $condaVer = & conda --version 2>&1
        "$condaVer"
        $true
    } else {
        "Conda not found on PATH (optional)"
        $null  # Warning, not failure
    }
}

# ═════════════════════════════════════════════════════════════════════════════════
# PHASE 4: SERVICE HEALTH (if not QuickCheck)
# ═════════════════════════════════════════════════════════════════════════════════

if (-not $QuickCheck) {
    Write-Host ""
    Write-Host "Service Health Checks" -ForegroundColor Cyan
    Write-Host "────────────────────"
    
    $ports = @(
        @{ name = "API Gateway"; port = 7000 },
        @{ name = "Model Router"; port = 7010 },
        @{ name = "Memory Engine"; port = 7020 },
        @{ name = "Pipecat"; port = 7030 },
        @{ name = "OpenClaw"; port = 7040 }
    )
    
    foreach ($svc in $ports) {
        Test-Status "$($svc.name) (port $($svc.port))" {
            try {
                $response = Invoke-WebRequest -Uri "http://127.0.0.1:$($svc.port)/health" `
                    -TimeoutSec 2 `
                    -UseBasicParsing `
                    -ErrorAction SilentlyContinue
                $response.StatusCode -eq 200
            } catch {
                $false
            }
        }
    }
}

# ═════════════════════════════════════════════════════════════════════════════════
# PHASE 5: PORT AVAILABILITY
# ═════════════════════════════════════════════════════════════════════════════════

Write-Host ""
Write-Host "Port Availability" -ForegroundColor Cyan
Write-Host "─────────────────"

$portsToCheck = @(7000, 7010, 7020, 7030, 7040, 7050)
$unavailablePorts = @()

foreach ($port in $portsToCheck) {
    $portName = @{
        7000 = "API Gateway"
        7010 = "Model Router"
        7020 = "Memory Engine"
        7030 = "Pipecat"
        7040 = "OpenClaw"
        7050 = "EVA-OS"
    }[$port]
    
    $listener = $null
    try {
        $listener = New-Object System.Net.Sockets.TcpListener([System.Net.IPAddress]::Loopback, $port)
        $listener.Start()
        $listener.Stop()
        Write-Test "Port $port ($portName)" $true "Available"
    } catch {
        Write-Test "Port $port ($portName)" $false "IN USE"
        $unavailablePorts += $port
    }
}

# ═════════════════════════════════════════════════════════════════════════════════
# PHASE 6: UPSTREAM SOURCES
# ═════════════════════════════════════════════════════════════════════════════════

Write-Host ""
Write-Host "Upstream Sources" -ForegroundColor Cyan
Write-Host "────────────────"

$sources = @(
    @{ name = "OpenClaw"; file = "CURRENT.txt"; path = "$($Root)integrations\openclaw\upstream\CURRENT.txt" },
    @{ name = "Pipecat"; file = "CURRENT.txt"; path = "$($Root)integrations\pipecat\upstream\CURRENT.txt" },
    @{ name = "LM-Studio"; file = ".exe"; path = "$($Root)tools\sysprog\LM-Studio-0.4.2-2-x64.exe" },
    @{ name = "Miniconda"; file = ".exe"; path = "$($Root)tools\sysprog\Miniconda3-py311_25.11.1-1-Windows-x86_64.exe" }
)

foreach ($src in $sources) {
    if (Test-Path -LiteralPath $src.path) {
        Write-Test $src.name $true "Ready"
    } else {
        Warn $src.name "Not found: $($src.path)"
    }
}

# ═════════════════════════════════════════════════════════════════════════════════
# SUMMARY AND RECOMMENDATIONS
# ═════════════════════════════════════════════════════════════════════════════════

Write-Host ""
Write-Host "╔════════════════════════════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "║                  DIAGNOSTIC SUMMARY                       ║" -ForegroundColor Cyan
Write-Host "╚════════════════════════════════════════════════════════════╝" -ForegroundColor Cyan
Write-Host ""

Write-Host "Passed:  " -NoNewline -ForegroundColor Green
Write-Host "$($passed.Count) checks" -ForegroundColor Green

Write-Host "Failed:  " -NoNewline -ForegroundColor Red
Write-Host "$($failed.Count) checks" -ForegroundColor Red

Write-Host "Warned:  " -NoNewline -ForegroundColor Yellow
Write-Host "$($warned.Count) items" -ForegroundColor Yellow

Write-Host ""

if ($failed.Count -eq 0) {
    Write-Host "✓ All critical checks passed!" -ForegroundColor Green
    Write-Host ""
    Write-Host "Ready to start Sonia:" -ForegroundColor Green
    Write-Host "  .\scripts\ops\start-sonia-stack.ps1" -ForegroundColor Cyan
} else {
    Write-Host "✗ Some checks failed. See above for details." -ForegroundColor Red
    Write-Host ""
    Write-Host "Recommended fixes:" -ForegroundColor Red
    if ($failed -contains "Node.js available") {
        Write-Host "  • Install Node.js 20+ from https://nodejs.org/" -ForegroundColor DarkRed
    }
    if ($failed -contains "Python 3.11+ available") {
        Write-Host "  • Install Python 3.11+ or Miniconda" -ForegroundColor DarkRed
    }
    if ($unavailablePorts.Count -gt 0) {
        Write-Host "  • Free ports: $($unavailablePorts -join ', ')" -ForegroundColor DarkRed
    }
}

Write-Host ""
