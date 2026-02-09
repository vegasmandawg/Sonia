<#
.SYNOPSIS
SONIA Stack Launcher v2 - Clean, minimal startup without syntax issues
#>

param(
    [string]$Root = "S:\",
    [switch]$SkipHealthCheck,
    [switch]$TestOnly
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

Write-Host "[SONIA] Starting Sonia Stack..." -ForegroundColor Cyan
Write-Host "[SONIA] Root: $Root" -ForegroundColor Cyan

# Ensure root has trailing backslash
if ($Root -and -not $Root.EndsWith("\")) { $Root = "$Root\" }

# Create required directories
$dirs = @(
    "$($Root)logs\services",
    "$($Root)state\pids",
    "$($Root)config",
    "$($Root)artifacts\phase3"
)

foreach ($dir in $dirs) {
    if (-not (Test-Path $dir)) {
        New-Item -ItemType Directory -Path $dir -Force | Out-Null
    }
}

Write-Host "[OK] Directories ready" -ForegroundColor Green

if (-not $TestOnly) {
    # Launch all services
    $services = @(
        "S:\scripts\ops\run-api-gateway.ps1",
        "S:\scripts\ops\run-model-router.ps1",
        "S:\scripts\ops\run-memory-engine.ps1",
        "S:\scripts\ops\run-pipecat.ps1",
        "S:\scripts\ops\run-openclaw.ps1"
    )
    
    foreach ($svc in $services) {
        if (Test-Path $svc) {
            Write-Host "[SONIA] Starting $svc..." -ForegroundColor Cyan
            try {
                & $svc -Root $Root
                Start-Sleep -Milliseconds 500
            } catch {
                Write-Host "[ERROR] Failed to start $svc : $_" -ForegroundColor Red
            }
        }
    }
}

if (-not $SkipHealthCheck -and -not $TestOnly) {
    Write-Host "[SONIA] Waiting for services to be healthy..." -ForegroundColor Cyan
    
    $ports = @(7000, 7010, 7020, 7030, 7040)
    $maxRetries = 60
    $retry = 0
    
    while ($retry -lt $maxRetries) {
        $healthy = 0
        
        foreach ($port in $ports) {
            try {
                $response = Invoke-WebRequest -Uri "http://127.0.0.1:$port/healthz" `
                    -TimeoutSec 2 -UseBasicParsing -ErrorAction SilentlyContinue
                
                if ($response.StatusCode -eq 200) {
                    $healthy++
                }
            } catch {
                # Service not ready yet
            }
        }
        
        if ($healthy -eq $ports.Count) {
            Write-Host "[OK] All services healthy" -ForegroundColor Green
            break
        }
        
        Start-Sleep -Milliseconds 500
        $retry++
    }
}

Write-Host "[OK] Sonia stack startup complete" -ForegroundColor Green
