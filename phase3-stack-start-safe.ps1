# Safe startup script for Phase 3 Gate 1
# ASCII-only version for compatibility

[CmdletBinding()]
param(
    [Parameter(Mandatory=$false)]
    [string]$Root = "S:\",
    
    [Parameter(Mandatory=$false)]
    [switch]$SkipHealthCheck
)

$ErrorActionPreference = "Continue"

Write-Host ""
Write-Host "=======================================================" -ForegroundColor Cyan
Write-Host "  SONIA STACK LAUNCHER (Safe ASCII Version)" -ForegroundColor Cyan
Write-Host "=======================================================" -ForegroundColor Cyan
Write-Host ""

# Validate directories
$root = $Root
if (-not (Test-Path -LiteralPath $root)) {
    Write-Host "[ERROR] Root directory not found: $root" -ForegroundColor Red
    exit 1
}

Write-Host "Starting services from: $root" -ForegroundColor Green
Write-Host ""

# Create required directories
if (-not (Test-Path "$root\state\pids")) { New-Item -ItemType Directory -Path "$root\state\pids" -Force | Out-Null }
if (-not (Test-Path "$root\logs\services")) { New-Item -ItemType Directory -Path "$root\logs\services" -Force | Out-Null }

# Define services
$services = @(
    @{ Name = "API Gateway"; Port = 7000; Script = "run-api-gateway.ps1" },
    @{ Name = "Model Router"; Port = 7010; Script = "run-model-router.ps1" },
    @{ Name = "Memory Engine"; Port = 7020; Script = "run-memory-engine.ps1" },
    @{ Name = "Pipecat"; Port = 7030; Script = "run-pipecat.ps1" },
    @{ Name = "OpenClaw"; Port = 7040; Script = "run-openclaw.ps1" }
)

# Check if EVA-OS exists and add if so
if (Test-Path "$root\services\eva-os") {
    $services += @{ Name = "EVA-OS"; Port = 7050; Script = "run-eva-os.ps1" }
}

Write-Host "Services to start: $($services.Count)" -ForegroundColor Gray
Write-Host ""

# Validate all scripts exist
$allValid = $true
foreach ($svc in $services) {
    $scriptPath = "$root\scripts\ops\$($svc.Script)"
    if (-not (Test-Path $scriptPath)) {
        Write-Host "[ERROR] Script not found: $($svc.Script)" -ForegroundColor Red
        $allValid = $false
    }
}

if (-not $allValid) {
    Write-Host "Validation failed" -ForegroundColor Red
    exit 1
}

Write-Host "All scripts validated" -ForegroundColor Green
Write-Host ""

# Start services
Write-Host "Starting services..." -ForegroundColor Cyan
Write-Host ""

$startedCount = 0
foreach ($svc in $services) {
    $scriptPath = "$root\scripts\ops\$($svc.Script)"
    try {
        Write-Host "  Starting $($svc.Name)..." -ForegroundColor Gray
        & $scriptPath -Root $root -ErrorAction SilentlyContinue | Out-Null
        $startedCount++
        Start-Sleep -Milliseconds 500
    } catch {
        Write-Host "  ERROR: Failed to start $($svc.Name)" -ForegroundColor Red
    }
}

Write-Host ""
Write-Host "Started $startedCount/$($services.Count) services" -ForegroundColor Green
Write-Host ""

# Health checks if requested
if (-not $SkipHealthCheck) {
    Write-Host "Waiting for services to be ready..." -ForegroundColor Cyan
    Write-Host ""
    
    foreach ($svc in $services) {
        $isHealthy = $false
        $attempts = 0
        $maxAttempts = 15
        
        while ($attempts -lt $maxAttempts) {
            try {
                $Response = Invoke-WebRequest -Uri "http://127.0.0.1:$($svc.Port)/healthz" -TimeoutSec 2 -ErrorAction Stop
                if ($Response.StatusCode -eq 200) {
                    $isHealthy = $true
                    break
                }
            } catch {
                # Not ready yet
            }
            $attempts++
            Start-Sleep -Milliseconds 200
        }
        
        if ($isHealthy) {
            Write-Host "  [OK] $($svc.Name) (port $($svc.Port))" -ForegroundColor Green
        } else {
            Write-Host "  [ERROR] $($svc.Name) (port $($svc.Port)) not responding" -ForegroundColor Red
        }
    }
}

Write-Host ""
Write-Host "=======================================================" -ForegroundColor Cyan
Write-Host "  STARTUP COMPLETE" -ForegroundColor Cyan
Write-Host "=======================================================" -ForegroundColor Cyan
Write-Host ""
