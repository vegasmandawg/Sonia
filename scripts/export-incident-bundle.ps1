<#
.SYNOPSIS
    Export incident bundle for post-mortem analysis.

.DESCRIPTION
    Collects logs, config snapshots, health checks, and diagnostics
    into a timestamped ZIP bundle for incident investigation.

    Collected artifacts:
      - Gateway, service, and error logs (last N minutes)
      - Health check snapshots from all services
      - Current sonia-config.json
      - Git status and recent commits
      - Diagnostics snapshot (if gateway running)
      - Circuit breaker and DLQ state

.PARAMETER WindowMinutes
    How far back to collect logs (default: 30 minutes).

.PARAMETER OutputDir
    Where to save the bundle (default: S:\incidents).

.EXAMPLE
    .\export-incident-bundle.ps1
    .\export-incident-bundle.ps1 -WindowMinutes 60
#>

param(
    [int]$WindowMinutes = 30,
    [string]$OutputDir = "S:\incidents"
)

$ErrorActionPreference = "Continue"
$ts = Get-Date -Format "yyyyMMdd-HHmmss"
$bundleDir = "$OutputDir\incident-$ts"

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Incident Bundle Export" -ForegroundColor Cyan
Write-Host "  Window: last $WindowMinutes minutes" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Create bundle directory
New-Item -ItemType Directory -Path $bundleDir -Force | Out-Null

# 1. Collect logs
Write-Host "[1/6] Collecting logs..." -ForegroundColor Yellow
$logDirs = @("S:\logs\gateway", "S:\logs")
foreach ($ld in $logDirs) {
    if (Test-Path $ld) {
        $cutoff = (Get-Date).AddMinutes(-$WindowMinutes)
        $files = Get-ChildItem $ld -File -Recurse | Where-Object { $_.LastWriteTime -ge $cutoff }
        if ($files) {
            $dest = "$bundleDir\logs\$(Split-Path $ld -Leaf)"
            New-Item -ItemType Directory -Path $dest -Force | Out-Null
            $files | Copy-Item -Destination $dest -Force
            Write-Host "  Copied $($files.Count) log files from $ld"
        }
    }
}

# 2. Config snapshot
Write-Host "[2/6] Saving config snapshot..." -ForegroundColor Yellow
$configDest = "$bundleDir\config"
New-Item -ItemType Directory -Path $configDest -Force | Out-Null
if (Test-Path "S:\config\sonia-config.json") {
    Copy-Item "S:\config\sonia-config.json" "$configDest\sonia-config.json"
    Write-Host "  Copied sonia-config.json"
}

# 3. Health checks
Write-Host "[3/6] Running health checks..." -ForegroundColor Yellow
$healthFile = "$bundleDir\health-checks.json"
$healthResults = @()
$ports = @(
    @{name="api-gateway"; port=7000},
    @{name="model-router"; port=7010},
    @{name="memory-engine"; port=7020},
    @{name="pipecat"; port=7030},
    @{name="openclaw"; port=7040},
    @{name="eva-os"; port=7050},
    @{name="vision-capture"; port=7060},
    @{name="perception"; port=7070}
)
foreach ($svc in $ports) {
    $entry = @{ service = $svc.name; port = $svc.port; status = "unreachable"; error = "" }
    try {
        $r = Invoke-RestMethod -Uri "http://127.0.0.1:$($svc.port)/healthz" -TimeoutSec 3
        $entry.status = $r.status
    } catch {
        $entry.error = $_.Exception.Message
    }
    $healthResults += $entry
}
$healthResults | ConvertTo-Json -Depth 3 | Set-Content $healthFile
Write-Host "  Checked $($ports.Count) services"

# 4. Git state
Write-Host "[4/6] Capturing git state..." -ForegroundColor Yellow
$gitFile = "$bundleDir\git-state.txt"
$gitInfo = @()
$gitInfo += "=== Branch ==="
$gitInfo += (git -C S:\ branch --show-current 2>&1)
$gitInfo += ""
$gitInfo += "=== Last 10 commits ==="
$gitInfo += (git -C S:\ log --oneline -10 2>&1)
$gitInfo += ""
$gitInfo += "=== Status ==="
$gitInfo += (git -C S:\ status --short 2>&1)
$gitInfo -join "`n" | Set-Content $gitFile
Write-Host "  Saved git state"

# 5. Diagnostics snapshot (if gateway running)
Write-Host "[5/6] Requesting diagnostics snapshot..." -ForegroundColor Yellow
try {
    $diag = Invoke-RestMethod -Uri "http://127.0.0.1:7000/v1/diagnostics/snapshot" -TimeoutSec 5
    $diag | ConvertTo-Json -Depth 5 | Set-Content "$bundleDir\diagnostics-snapshot.json"
    Write-Host "  Saved diagnostics snapshot"
} catch {
    Write-Host "  Gateway not reachable, skipping diagnostics" -ForegroundColor DarkYellow
}

# 6. Summary
Write-Host "[6/6] Writing summary..." -ForegroundColor Yellow
$summary = @{
    timestamp = (Get-Date).ToUniversalTime().ToString("o")
    window_minutes = $WindowMinutes
    hostname = $env:COMPUTERNAME
    bundle_path = $bundleDir
    branch = (git -C S:\ branch --show-current 2>$null)
    commit = (git -C S:\ rev-parse --short HEAD 2>$null)
}
$summary | ConvertTo-Json | Set-Content "$bundleDir\bundle-summary.json"

Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host "  Bundle saved: $bundleDir" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
