<#
.SYNOPSIS
    Export a diagnostic incident bundle for a given time window.
.DESCRIPTION
    Packages all relevant diagnostics into a timestamped archive:
    - Service health snapshots (all 6 services + supervisor summary)
    - Circuit breaker states and time-series metrics
    - Dead letter queue records
    - Recent actions timeline
    - JSONL logs (sessions, turns, tools, errors)
    - Dependency manifest and frozen requirements
    - Audit trails

    Usage:
      .\export-incident-bundle.ps1                        # Last 1 hour
      .\export-incident-bundle.ps1 -WindowMinutes 30      # Last 30 minutes
      .\export-incident-bundle.ps1 -OutputDir S:\tmp      # Custom output dir
.PARAMETER WindowMinutes
    Time window in minutes to include in the bundle (default: 60).
.PARAMETER OutputDir
    Base directory for the bundle (default: S:\incidents).
#>
param(
    [int]$WindowMinutes = 60,
    [string]$OutputDir = "S:\incidents"
)

$ErrorActionPreference = "Stop"
$GW = "http://127.0.0.1:7000"
$ts = Get-Date -Format "yyyyMMdd-HHmmss"
$bundleDir = "$OutputDir\incident-$ts"

Write-Host "`n=== Incident Bundle Export ==="
Write-Host "  Time window: last $WindowMinutes minutes"
Write-Host "  Bundle dir:  $bundleDir"
Write-Host "  Timestamp:   $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')`n"

# Create bundle directory structure
New-Item -ItemType Directory -Path "$bundleDir\health" -Force | Out-Null
New-Item -ItemType Directory -Path "$bundleDir\breakers" -Force | Out-Null
New-Item -ItemType Directory -Path "$bundleDir\dlq" -Force | Out-Null
New-Item -ItemType Directory -Path "$bundleDir\actions" -Force | Out-Null
New-Item -ItemType Directory -Path "$bundleDir\logs" -Force | Out-Null
New-Item -ItemType Directory -Path "$bundleDir\config" -Force | Out-Null
New-Item -ItemType Directory -Path "$bundleDir\audit" -Force | Out-Null

$errors = @()

# ---- 1. Service Health Snapshots ----
Write-Host "[1/8] Capturing service health..."
$services = @(
    @{ name = "api-gateway"; port = 7000 },
    @{ name = "model-router"; port = 7010 },
    @{ name = "memory-engine"; port = 7020 },
    @{ name = "pipecat"; port = 7030 },
    @{ name = "openclaw"; port = 7040 },
    @{ name = "eva-os"; port = 7050 }
)

$healthData = @{}
foreach ($svc in $services) {
    try {
        $h = Invoke-RestMethod -Uri "http://127.0.0.1:$($svc.port)/healthz" -TimeoutSec 5
        $healthData[$svc.name] = @{ status = "healthy"; port = $svc.port; response = $h }
    } catch {
        $healthData[$svc.name] = @{ status = "unreachable"; port = $svc.port; error = $_.ToString() }
    }
}
$healthData | ConvertTo-Json -Depth 5 | Out-File -Encoding utf8 "$bundleDir\health\services.json"

# Health supervisor summary
try {
    $summary = Invoke-RestMethod -Uri "$GW/v1/health/summary" -TimeoutSec 5
    $summary | ConvertTo-Json -Depth 5 | Out-File -Encoding utf8 "$bundleDir\health\supervisor-summary.json"
    Write-Host "  [OK] Health snapshots captured"
} catch {
    $errors += "health_supervisor: $_"
    Write-Host "  [WARN] Health supervisor unavailable"
}

# ---- 2. Circuit Breaker States + Metrics ----
Write-Host "[2/8] Capturing breaker states and metrics..."
try {
    $breakers = Invoke-RestMethod -Uri "$GW/v1/breakers" -TimeoutSec 5
    $breakers | ConvertTo-Json -Depth 5 | Out-File -Encoding utf8 "$bundleDir\breakers\states.json"
} catch {
    $errors += "breakers: $_"
}

try {
    $metrics = Invoke-RestMethod -Uri "$GW/v1/breakers/metrics?last_n=200" -TimeoutSec 5
    $metrics | ConvertTo-Json -Depth 10 | Out-File -Encoding utf8 "$bundleDir\breakers\metrics.json"
    Write-Host "  [OK] Breaker data captured"
} catch {
    $errors += "breaker_metrics: $_"
    Write-Host "  [WARN] Breaker metrics unavailable"
}

# ---- 3. Dead Letter Queue ----
Write-Host "[3/8] Capturing dead letter queue..."
try {
    $dlq = Invoke-RestMethod -Uri "$GW/v1/dead-letters?limit=500&include_replayed=true" -TimeoutSec 10
    $dlq | ConvertTo-Json -Depth 10 | Out-File -Encoding utf8 "$bundleDir\dlq\dead-letters.json"
    Write-Host "  [OK] $($dlq.total) dead letters captured"
} catch {
    $errors += "dlq: $_"
    Write-Host "  [WARN] DLQ unavailable"
}

# ---- 4. Recent Actions Timeline ----
Write-Host "[4/8] Capturing action timeline..."
try {
    $actions = Invoke-RestMethod -Uri "$GW/v1/actions?limit=200" -TimeoutSec 10
    $actions | ConvertTo-Json -Depth 10 | Out-File -Encoding utf8 "$bundleDir\actions\recent-actions.json"
    Write-Host "  [OK] $($actions.total) actions captured"
} catch {
    $errors += "actions: $_"
    Write-Host "  [WARN] Actions unavailable"
}

# Pending actions
try {
    $pending = Invoke-RestMethod -Uri "$GW/v1/actions?state=pending_approval&limit=50" -TimeoutSec 5
    $pending | ConvertTo-Json -Depth 10 | Out-File -Encoding utf8 "$bundleDir\actions\pending-actions.json"
} catch {
    # Non-critical
}

# ---- 5. JSONL Logs (filtered by time window) ----
Write-Host "[5/8] Capturing JSONL logs..."
$logDir = "S:\logs\gateway"
$logFiles = @("sessions.jsonl", "turns.jsonl", "tools.jsonl", "errors.jsonl", "dead_letters.jsonl", "actions.jsonl")
$cutoffTime = (Get-Date).AddMinutes(-$WindowMinutes)
$cutoffIso = $cutoffTime.ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ss")

foreach ($logFile in $logFiles) {
    $srcPath = Join-Path $logDir $logFile
    $dstPath = Join-Path "$bundleDir\logs" $logFile
    if (Test-Path $srcPath) {
        # Filter log entries within time window
        $filtered = @()
        try {
            Get-Content $srcPath -Encoding utf8 | ForEach-Object {
                try {
                    $entry = $_ | ConvertFrom-Json
                    $entryTs = $entry.ts
                    if ($entryTs -and $entryTs -ge $cutoffIso) {
                        $filtered += $_
                    }
                } catch {
                    # Skip malformed lines
                }
            }
        } catch {
            # If filtering fails, copy entire file
            $filtered = Get-Content $srcPath -Encoding utf8
        }
        if ($filtered.Count -gt 0) {
            $filtered | Out-File -Encoding utf8 $dstPath
        }
        Write-Host "  $logFile : $($filtered.Count) entries in window"
    } else {
        Write-Host "  $logFile : not found"
    }
}

# ---- 6. Configuration / Dependency Manifest ----
Write-Host "[6/8] Capturing configuration..."
if (Test-Path "S:\config\requirements-frozen.txt") {
    Copy-Item "S:\config\requirements-frozen.txt" "$bundleDir\config\" -Force
}
if (Test-Path "S:\config\dependency-lock.json") {
    Copy-Item "S:\config\dependency-lock.json" "$bundleDir\config\" -Force
}
if (Test-Path "S:\config\sonia-config.json") {
    Copy-Item "S:\config\sonia-config.json" "$bundleDir\config\" -Force
}
Write-Host "  [OK] Config files captured"

# ---- 7. Audit Trails ----
Write-Host "[7/8] Capturing audit trails..."
try {
    $audit = Invoke-RestMethod -Uri "$GW/v1/audit-trails?limit=200" -TimeoutSec 10
    $audit | ConvertTo-Json -Depth 10 | Out-File -Encoding utf8 "$bundleDir\audit\trails.json"
    Write-Host "  [OK] $($audit.total) audit trails captured"
} catch {
    $errors += "audit: $_"
    Write-Host "  [WARN] Audit trails unavailable"
}

# ---- 8. Bundle Metadata ----
Write-Host "[8/8] Writing bundle metadata..."
$meta = @{
    bundle_id = "incident-$ts"
    created_at = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
    window_minutes = $WindowMinutes
    window_start = $cutoffTime.ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
    window_end = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
    git_commit = (git rev-parse HEAD 2>$null)
    git_tag = try { git describe --tags --exact-match 2>$null } catch { "none" }
    python_version = (& 'S:\envs\sonia-core\python.exe' --version 2>&1).ToString().Replace("Python ", "")
    capture_errors = $errors
    file_count = (Get-ChildItem -Path $bundleDir -Recurse -File).Count
}
$meta | ConvertTo-Json -Depth 5 | Out-File -Encoding utf8 "$bundleDir\metadata.json"

# ---- Summary ----
$fileCount = (Get-ChildItem -Path $bundleDir -Recurse -File).Count
$totalSize = (Get-ChildItem -Path $bundleDir -Recurse -File | Measure-Object -Property Length -Sum).Sum
$totalSizeKB = [math]::Round($totalSize / 1024, 1)

Write-Host "`n=== Bundle Summary ==="
Write-Host "  Location: $bundleDir"
Write-Host "  Files:    $fileCount"
Write-Host "  Size:     $totalSizeKB KB"
Write-Host "  Errors:   $($errors.Count)"

if ($errors.Count -gt 0) {
    Write-Host "`n  Capture errors:"
    foreach ($e in $errors) {
        Write-Host "    - $e"
    }
}

Write-Host "`n[OK] Incident bundle exported to $bundleDir"
