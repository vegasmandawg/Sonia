<#
.SYNOPSIS
Capture baseline artifacts for bootable-1.0.0 snapshot

.DESCRIPTION
Creates a bundle containing:
- PID list (all services)
- Health responses (all endpoints)
- 200-line tail of each service log
- Timestamp and environment info

This serves as the baseline for regression testing.

.PARAMETER Root
Sonia root directory. Defaults to S:\

.PARAMETER OutputDir
Where to save artifacts. Defaults to S:\artifacts\baseline\

.EXAMPLE
.\capture-baseline-artifacts.ps1
.\capture-baseline-artifacts.ps1 -Root "D:\sonia" -OutputDir "D:\backups\baseline"
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory=$false)]
    [string]$Root = "S:\",

    [Parameter(Mandatory=$false)]
    [string]$OutputDir = "S:\artifacts\baseline"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$root = $Root
if (-not $root.EndsWith("\")) { $root = "$root\" }

Write-Host ""
Write-Host "+-------------------------------------------------------+" -ForegroundColor Cyan
Write-Host "|    BASELINE ARTIFACT CAPTURE (bootable-1.0.0)        |" -ForegroundColor Cyan
Write-Host "+-------------------------------------------------------+" -ForegroundColor Cyan
Write-Host ""

# Create output directory
New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null
Write-Host "[OK] Output directory: $OutputDir" -ForegroundColor Green

# -----------------------------------------------------------------------------
# 1. PID List
# -----------------------------------------------------------------------------

Write-Host ""
Write-Host "Capturing PID list..." -ForegroundColor Cyan

$pidDir = Join-Path $root "state\pids"
$pidList = @()

if (Test-Path -LiteralPath $pidDir) {
    Get-ChildItem -Path $pidDir -Filter "*.pid" | ForEach-Object {
        $serviceName = $_.BaseName
        $procId = Get-Content -LiteralPath $_.FullName -ErrorAction SilentlyContinue
        if ($procId) {
            $pidList += @{
                service = $serviceName
                pid = $procId
                timestamp = Get-Date -Format "yyyy-MM-ddTHH:mm:ss.fffZ"
            }
            Write-Host "  [$serviceName] PID: $procId" -ForegroundColor Green
        }
    }
}

$pidList | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $OutputDir "pids.json") -Encoding UTF8
Write-Host "[OK] PID list saved" -ForegroundColor Green

# -----------------------------------------------------------------------------
# 2. Health Responses
# -----------------------------------------------------------------------------

Write-Host ""
Write-Host "Capturing health responses..." -ForegroundColor Cyan

$healthResponses = @{}
$ports = @(7000, 7010, 7020, 7030, 7040, 7050)
$portNames = @("api-gateway", "model-router", "memory-engine", "pipecat", "openclaw", "eva-os")

for ($i = 0; $i -lt $ports.Count; $i++) {
    $port = $ports[$i]
    $serviceName = $portNames[$i]
    $url = "http://127.0.0.1:$port/healthz"
    
    try {
        $response = Invoke-WebRequest -Uri $url -TimeoutSec 2 -UseBasicParsing -ErrorAction Stop
        if ($response.StatusCode -eq 200) {
            $body = $response.Content | ConvertFrom-Json
            $healthResponses[$serviceName] = @{
                status = "ok"
                port = $port
                response = $body
                timestamp = Get-Date -Format "yyyy-MM-ddTHH:mm:ss.fffZ"
            }
            Write-Host "  [${serviceName}:${port}] [OK] Healthy" -ForegroundColor Green
        }
    } catch {
        $healthResponses[$serviceName] = @{
            status = "failed"
            port = $port
            error = $_.Exception.Message
            timestamp = Get-Date -Format "yyyy-MM-ddTHH:mm:ss.fffZ"
        }
        Write-Host "  [${serviceName}:${port}] [FAIL] Failed" -ForegroundColor Red
    }
}

$healthResponses | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $OutputDir "health-responses.json") -Encoding UTF8
Write-Host "[OK] Health responses saved" -ForegroundColor Green

# -----------------------------------------------------------------------------
# 3. Service Logs (200-line tail)
# -----------------------------------------------------------------------------

Write-Host ""
Write-Host "Capturing service logs..." -ForegroundColor Cyan

$logsDir = Join-Path $root "logs\services"

if (Test-Path -LiteralPath $logsDir) {
    Get-ChildItem -Path $logsDir -Filter "*.out.log" | ForEach-Object {
        $serviceName = $_.BaseName -replace "\.out", ""
        $logContent = Get-Content -LiteralPath $_.FullName -Tail 200 -ErrorAction SilentlyContinue
        
        $outputFile = Join-Path $OutputDir "$serviceName.log"
        if ($logContent) {
            $logContent | Set-Content -LiteralPath $outputFile -Encoding UTF8
            Write-Host "  [$serviceName] $(if ($logContent -is [array]) { $logContent.Count } else { 1 }) lines" -ForegroundColor Green
        }
    }
}

Write-Host "[OK] Service logs saved" -ForegroundColor Green

# -----------------------------------------------------------------------------
# 4. Metadata
# -----------------------------------------------------------------------------

Write-Host ""
Write-Host "Capturing metadata..." -ForegroundColor Cyan

$metadata = @{
    snapshot = "bootable-1.0.0"
    timestamp = Get-Date -Format "yyyy-MM-ddTHH:mm:ss.fffZ"
    root = $root
    python_version = (python --version 2>&1)
    powershell_version = $PSVersionTable.PSVersion.ToString()
    windows_version = (Get-WmiObject -Class Win32_OperatingSystem).Caption
    services = @{
        count = 6
        ports = @(7000, 7010, 7020, 7030, 7040, 7050)
        names = @("api-gateway", "model-router", "memory-engine", "pipecat", "openclaw", "eva-os")
    }
    contract = "BOOT_CONTRACT.md"
}

$metadata | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $OutputDir "metadata.json") -Encoding UTF8
Write-Host "[OK] Metadata saved" -ForegroundColor Green

# -----------------------------------------------------------------------------
# 5. Summary
# -----------------------------------------------------------------------------

Write-Host ""
Write-Host "+-------------------------------------------------------+" -ForegroundColor Cyan
Write-Host "|                    ARTIFACTS CAPTURED                 |" -ForegroundColor Cyan
Write-Host "+-------------------------------------------------------+" -ForegroundColor Cyan
Write-Host ""

$artifacts = Get-ChildItem -Path $OutputDir
Write-Host "Files saved:" -ForegroundColor Cyan
$artifacts | ForEach-Object {
    $size = if ($_.Length -gt 1MB) { "$([math]::Round($_.Length/1MB, 1)) MB" } elseif ($_.Length -gt 1KB) { "$([math]::Round($_.Length/1KB, 1)) KB" } else { "$($_.Length) B" }
    Write-Host "  - $($_.Name) ($size)" -ForegroundColor Gray
}

Write-Host ""
Write-Host "Total artifacts:" -ForegroundColor Cyan
Write-Host "  PIDs:       pids.json" -ForegroundColor Gray
Write-Host "  Health:     health-responses.json" -ForegroundColor Gray
Write-Host "  Logs:       *.log (6 service log tails)" -ForegroundColor Gray
Write-Host "  Metadata:   metadata.json" -ForegroundColor Gray
Write-Host ""

Write-Host "Baseline frozen: $OutputDir" -ForegroundColor Green
Write-Host ""
