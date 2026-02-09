<#
.SYNOPSIS
Start the complete Sonia stack

.DESCRIPTION
Starts all Sonia services in order:
  1. API Gateway (7000)
  2. Model Router (7010)
  3. Memory Engine (7020)
  4. Pipecat (7030)
  5. OpenClaw (7040)
  6. EVA-OS (7050) - optional

Performs health checks after startup and displays logs.

.PARAMETER Root
Sonia root directory. Defaults to S:\

.PARAMETER Reload
Enable auto-reload for development (passes -Reload to each service)

.PARAMETER SkipHealthCheck
Skip health checks after startup

.PARAMETER TestOnly
Test configuration without starting services

.EXAMPLE
.\start-sonia-stack.ps1
.\start-sonia-stack.ps1 -Reload
.\start-sonia-stack.ps1 -SkipHealthCheck
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory=$false)]
    [string]$Root = "S:\",

    [Parameter(Mandatory=$false)]
    [switch]$Reload,

    [Parameter(Mandatory=$false)]
    [switch]$SkipHealthCheck,

    [Parameter(Mandatory=$false)]
    [switch]$TestOnly,

    [Parameter(Mandatory=$false)]
    [int]$HealthCheckTimeoutSeconds = 30
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# Import library
. (Join-Path $Root "scripts\lib\sonia-stack.ps1")

# ─────────────────────────────────────────────────────────────────────────────
# Setup
# ─────────────────────────────────────────────────────────────────────────────

$root = Get-SoniaRoot $Root
Write-Host ""
Write-Host "╔═════════════════════════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "║           SONIA STACK LAUNCHER                          ║" -ForegroundColor Cyan
Write-Host "╚═════════════════════════════════════════════════════════╝" -ForegroundColor Cyan
Write-Host ""
Write-Host "Root: $root" -ForegroundColor Gray
Write-Host "Reload: $(if ($Reload) { 'ENABLED' } else { 'disabled' })" -ForegroundColor Gray
Write-Host "Health checks: $(if ($SkipHealthCheck) { 'disabled' } else { 'ENABLED' })" -ForegroundColor Gray
Write-Host ""

# Validate root
if (-not (Test-Path -LiteralPath $root)) {
    Write-Host "[✗] Root directory not found: $root" -ForegroundColor Red
    exit 1
}

# Create required directories
Ensure-Dir (Join-Path $root "state\pids") | Out-Null
Ensure-Dir (Join-Path $root "logs\services") | Out-Null

# Define services
$services = @(
    @{ Name = "API Gateway"; Script = "run-api-gateway.ps1"; Port = 7000 },
    @{ Name = "Model Router"; Script = "run-model-router.ps1"; Port = 7010 },
    @{ Name = "Memory Engine"; Script = "run-memory-engine.ps1"; Port = 7020 },
    @{ Name = "Pipecat"; Script = "run-pipecat.ps1"; Port = 7030 },
    @{ Name = "OpenClaw"; Script = "run-openclaw.ps1"; Port = 7040 }
)

# Check if EVA-OS exists
$evaOsDir = Join-Path $root "services\eva-os"
if (Test-Path -LiteralPath $evaOsDir) {
    $services += @{ Name = "EVA-OS"; Script = "run-eva-os.ps1"; Port = 7050 }
}

# ─────────────────────────────────────────────────────────────────────────────
# Validation Phase
# ─────────────────────────────────────────────────────────────────────────────

Write-Host "Phase 0: Validation" -ForegroundColor Cyan
Write-Host "──────────────────────────────────────────────────────────"

$allValid = $true
foreach ($svc in $services) {
    $scriptPath = Join-Path $root "scripts\ops\$($svc.Script)"
    if (-not (Test-Path -LiteralPath $scriptPath)) {
        Write-Host "[✗] Script not found: $($svc.Script)" -ForegroundColor Red
        $allValid = $false
    } else {
        Write-Host "[✓] $($svc.Name) script exists" -ForegroundColor Green
    }
}

if (-not $allValid) {
    Write-Host ""
    Write-Host "[✗] Validation failed" -ForegroundColor Red
    exit 1
}

Write-Host "[✓] All startup scripts found" -ForegroundColor Green
Write-Host ""

if ($TestOnly) {
    Write-Host "Test mode: configuration valid, not starting services" -ForegroundColor Yellow
    exit 0
}

# ─────────────────────────────────────────────────────────────────────────────
# Startup Phase
# ─────────────────────────────────────────────────────────────────────────────

Write-Host "Phase 1: Startup" -ForegroundColor Cyan
Write-Host "──────────────────────────────────────────────────────────"

$startedServices = @()
$failedServices = @()

foreach ($svc in $services) {
    $scriptPath = Join-Path $root "scripts\ops\$($svc.Script)"
    
    try {
        Write-Host "Starting $($svc.Name)..." -ForegroundColor Gray
        
        # Runner scripts are self-contained; invoke directly
        & $scriptPath
        $startedServices += $svc
        Start-Sleep -Milliseconds 500
    }
    catch {
        Write-Host "[✗] Failed to start $($svc.Name): $_" -ForegroundColor Red
        $failedServices += $svc
    }
}

Write-Host ""

# ─────────────────────────────────────────────────────────────────────────────
# Health Check Phase
# ─────────────────────────────────────────────────────────────────────────────

if (-not $SkipHealthCheck) {
    Write-Host "Phase 2: Health Check" -ForegroundColor Cyan
    Write-Host "──────────────────────────────────────────────────────────"
    Write-Host "Waiting up to ${HealthCheckTimeoutSeconds}s for services to be ready..." -ForegroundColor Gray
    Write-Host ""
    
    $stopwatch = [System.Diagnostics.Stopwatch]::StartNew()
    $healthyCount = 0
    
    foreach ($svc in $startedServices) {
        $isHealthy = $false
        $elapsed = 0
        
        while ($stopwatch.Elapsed.TotalSeconds -lt $HealthCheckTimeoutSeconds) {
            if (Test-SoniaServiceHealth -Port $svc.Port) {
                $isHealthy = $true
                break
            }
            Start-Sleep -Milliseconds 200
        }
        
        $elapsed = [Math]::Round($stopwatch.Elapsed.TotalSeconds, 1)
        
        if ($isHealthy) {
            Write-Host "[✓] $($svc.Name) (port $($svc.Port))" -ForegroundColor Green
            $healthyCount++
        } else {
            Write-Host "[✗] $($svc.Name) (port $($svc.Port)) - not responding" -ForegroundColor Red
        }
    }
    
    Write-Host ""
    Write-Host "Health check completed in ${elapsed}s ($healthyCount/$($startedServices.Count) healthy)" -ForegroundColor Gray
}

# ─────────────────────────────────────────────────────────────────────────────
# Summary
# ─────────────────────────────────────────────────────────────────────────────

Write-Host ""
Write-Host "╔═════════════════════════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "║           STARTUP COMPLETE                              ║" -ForegroundColor Cyan
Write-Host "╚═════════════════════════════════════════════════════════╝" -ForegroundColor Cyan
Write-Host ""

if ($failedServices.Count -gt 0) {
    Write-Host "⚠ Failed services: $($failedServices.Name -join ', ')" -ForegroundColor Yellow
}

Write-Host "Started services: $($startedServices.Name -join ', ')" -ForegroundColor Green
Write-Host ""

Write-Host "Service Endpoints:" -ForegroundColor Cyan
foreach ($svc in $startedServices) {
    Write-Host "  $($svc.Name): http://127.0.0.1:$($svc.Port)" -ForegroundColor Gray
}
Write-Host ""

Write-Host "Log files: $root\logs\services\" -ForegroundColor Gray
Write-Host "PID files: $root\state\pids\" -ForegroundColor Gray
Write-Host ""

Write-Host "Next steps:" -ForegroundColor Cyan
Write-Host "  Check health: iwr http://127.0.0.1:7000/healthz" -ForegroundColor Gray
Write-Host "  Stop all:     .\stop-sonia-stack.ps1" -ForegroundColor Gray
Write-Host "  View logs:    Get-Content $root\logs\services\api-gateway.out.log -Wait -Tail 20" -ForegroundColor Gray
Write-Host ""
