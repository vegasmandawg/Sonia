<#
.SYNOPSIS
48-hour soak monitor for Sonia Stack RC-1.

.DESCRIPTION
Runs continuously, capturing snapshots every 15 minutes and checkpoint
summaries every 60 minutes. Aborts on Sev-1/Sev-2 events.

Must be started AFTER T0 baseline is captured by soak-start.ps1.

.EXAMPLE
.\soak-monitor.ps1 -DurationHours 48
#>

[CmdletBinding()]
param(
    [int]$DurationHours = 48,
    [int]$SnapshotIntervalMinutes = 15,
    [int]$CheckpointIntervalMinutes = 60
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

# Global error trap: write crash details to file
trap {
    $crashMsg = @(
        "=== SOAK MONITOR CRASH ==="
        "Time: $(Get-Date -Format 'o')"
        "Error: $($_.Exception.Message)"
        "Line: $($_.InvocationInfo.ScriptLineNumber)"
        "Stack: $($_.ScriptStackTrace)"
    )
    $crashMsg | Out-File -FilePath "S:\artifacts\phase3\soak\monitor-crash.txt" -Encoding UTF8
    exit 1
}

$SoakDir = "S:\artifacts\phase3\soak"
$SnapshotDir = Join-Path $SoakDir "snapshots"
$CheckpointDir = Join-Path $SoakDir "checkpoints"
$LogFile = Join-Path $SoakDir "soak-monitor.log"

New-Item -ItemType Directory -Path $SnapshotDir -Force | Out-Null
New-Item -ItemType Directory -Path $CheckpointDir -Force | Out-Null

$ServiceSpec = @(
    @{ Name="api-gateway"; Port=7000; Pid="S:\state\pids\api-gateway.pid" },
    @{ Name="model-router"; Port=7010; Pid="S:\state\pids\model-router.pid" },
    @{ Name="memory-engine"; Port=7020; Pid="S:\state\pids\memory-engine.pid" },
    @{ Name="pipecat"; Port=7030; Pid="S:\state\pids\pipecat.pid" },
    @{ Name="openclaw"; Port=7040; Pid="S:\state\pids\openclaw.pid" },
    @{ Name="eva-os"; Port=7050; Pid="S:\state\pids\eva-os.pid" }
)

# Load T0 baseline
$BaselineFile = Join-Path $SoakDir "t0-baseline.json"
if (-not (Test-Path $BaselineFile)) {
    Write-Host "[FATAL] T0 baseline not found at $BaselineFile. Run soak-start.ps1 first." -ForegroundColor Red
    exit 1
}
$Baseline = Get-Content $BaselineFile -Raw | ConvertFrom-Json

function Log {
    param([string]$Message, [string]$Level = "INFO")
    $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') [$Level] $Message"
    Write-Host $line
    Add-Content -Path $LogFile -Value $line
}

function Get-ServiceSnapshot {
    param([hashtable]$svc)

    $result = @{
        Name = $svc.Name
        Port = $svc.Port
        Healthy = $false
        PID = $null
        PIDMatch = $false
        RSS_KB = $null
        Handles = $null
        Threads = $null
    }

    # Check PID
    if (Test-Path $svc.Pid) {
        try {
            $result.PID = [int](Get-Content $svc.Pid -ErrorAction Stop | Select-Object -First 1)
        } catch { }
    }

    # Check process metrics
    if ($result.PID) {
        $proc = Get-Process -Id $result.PID -ErrorAction SilentlyContinue
        if ($proc) {
            $result.RSS_KB = [math]::Round($proc.WorkingSet64 / 1024)
            $result.Handles = $proc.HandleCount
            $result.Threads = $proc.Threads.Count
        }
    }

    # Check healthz
    try {
        $resp = Invoke-WebRequest -Uri "http://127.0.0.1:$($svc.Port)/healthz" -TimeoutSec 5 -UseBasicParsing -ErrorAction Stop
        $result.Healthy = ($resp.StatusCode -eq 200)
    } catch { }

    # Check PID matches baseline
    $baselinePIDs = @($Baseline.pids.PSObject.Properties | ForEach-Object { $_ })
    $baselineEntry = $baselinePIDs | Where-Object { $_.Name -eq $svc.Name }
    if ($baselineEntry -and $result.PID -eq $baselineEntry.Value) {
        $result.PIDMatch = $true
    }

    return $result
}

function Get-LogBurst {
    param([int]$WindowMinutes = 15)
    $pattern = "(FATAL|CRITICAL|Traceback|panic|SIGSEGV|unhandled exception)"
    $count = 0
    $matches_found = @()

    Get-ChildItem "S:\logs\services\*.err.log" -ErrorAction SilentlyContinue | ForEach-Object {
        $content = Get-Content $_.FullName -Tail 200 -ErrorAction SilentlyContinue
        if ($content) {
            $hits = @($content | Select-String $pattern)
            $count += $hits.Count
            foreach ($h in $hits) {
                $matches_found += "$($_.Name): $($h.Line)"
            }
        }
    }

    return @{
        Count = $count
        Matches = $matches_found
    }
}

function Test-ConfigDrift {
    if (Test-Path "S:\config\sonia-config.json") {
        $currentHash = (Get-FileHash -LiteralPath "S:\config\sonia-config.json" -Algorithm SHA256).Hash
        return @{
            CurrentHash = $currentHash
            BaselineHash = $Baseline.config_hash
            Drifted = ($currentHash -ne $Baseline.config_hash)
        }
    }
    return @{ CurrentHash = "NOT_FOUND"; BaselineHash = $Baseline.config_hash; Drifted = ($Baseline.config_hash -ne "NOT_FOUND") }
}

function Write-Snapshot {
    param([string]$Tag)

    $stamp = Get-Date -Format "yyyyMMdd_HHmmss"
    $snapshots = @()
    $sevEvents = @()

    foreach ($svc in $ServiceSpec) {
        $snap = Get-ServiceSnapshot $svc
        $snapshots += $snap

        # Sev-1: Service down or PID changed
        if (-not $snap.Healthy) {
            $sevEvents += @{ Severity = "SEV-1"; Service = $svc.Name; Detail = "healthz FAILED" }
        }
        if ($snap.PID -and -not $snap.PIDMatch) {
            $sevEvents += @{ Severity = "SEV-1"; Service = $svc.Name; Detail = "PID changed: baseline=$($Baseline.pids.($svc.Name)) current=$($snap.PID)" }
        }

        # Sev-2: RSS/handle/thread drift
        $baselineRSS = $Baseline.metrics | Where-Object { $_.Name -eq $svc.Name } | Select-Object -ExpandProperty RSS_KB -ErrorAction SilentlyContinue
        if ($baselineRSS -and $snap.RSS_KB) {
            $drift = (($snap.RSS_KB - $baselineRSS) / $baselineRSS) * 100
            if ($drift -gt 50) {
                $sevEvents += @{ Severity = "SEV-2"; Service = $svc.Name; Detail = "RSS drift ${drift:N1}% (baseline=${baselineRSS}KB current=$($snap.RSS_KB)KB)" }
            }
        }
        $baselineHandles = $Baseline.metrics | Where-Object { $_.Name -eq $svc.Name } | Select-Object -ExpandProperty Handles -ErrorAction SilentlyContinue
        if ($baselineHandles -and $snap.Handles) {
            $hDrift = $snap.Handles - $baselineHandles
            if ($hDrift -gt 500) {
                $sevEvents += @{ Severity = "SEV-2"; Service = $svc.Name; Detail = "Handle drift +$hDrift (baseline=$baselineHandles current=$($snap.Handles))" }
            }
        }
    }

    # Log burst check
    $logBurst = Get-LogBurst
    if ($logBurst.Count -gt 0) {
        $sevEvents += @{ Severity = "SEV-2"; Service = "logs"; Detail = "$($logBurst.Count) fatal/traceback entries in error logs" }
    }

    # Config drift check
    $configCheck = Test-ConfigDrift
    if ($configCheck.Drifted) {
        $sevEvents += @{ Severity = "SEV-1"; Service = "config"; Detail = "Config hash drift: baseline=$($configCheck.BaselineHash) current=$($configCheck.CurrentHash)" }
    }

    # Build snapshot object
    $snapshotObj = @{
        timestamp = Get-Date -Format "o"
        tag = $Tag
        elapsed_hours = [math]::Round(((Get-Date) - [datetime]$Baseline.start_time).TotalHours, 2)
        services = $snapshots
        config_drift = $configCheck
        log_burst = @{ count = $logBurst.Count }
        sev_events = $sevEvents
        all_healthy = ($sevEvents.Count -eq 0)
    }

    # Write snapshot file
    $snapshotFile = Join-Path $SnapshotDir "snapshot-$stamp.json"
    $snapshotObj | ConvertTo-Json -Depth 4 | Out-File -FilePath $snapshotFile -Encoding UTF8

    # Log summary
    $healthyCount = @($snapshots | Where-Object { $_.Healthy }).Count
    Log "[$Tag] Snapshot ${stamp}: $healthyCount/6 healthy, $($sevEvents.Count) sev events, elapsed=$($snapshotObj.elapsed_hours)h" $(if ($sevEvents.Count -gt 0) { "WARN" } else { "PASS" })

    foreach ($sev in $sevEvents) {
        Log "  $($sev.Severity): $($sev.Service) - $($sev.Detail)" "FAIL"
    }

    return $snapshotObj
}

function Write-Checkpoint {
    param([int]$CheckpointNum)

    $stamp = Get-Date -Format "yyyyMMdd_HHmmss"
    Log "=== CHECKPOINT $CheckpointNum ($(Get-Date -Format 'HH:mm:ss')) ===" "HEADER"

    # Take a fresh snapshot first
    $snap = Write-Snapshot -Tag "checkpoint-$CheckpointNum"

    # Compute cumulative stats from all snapshots
    $allSnapshots = Get-ChildItem $SnapshotDir -Filter "snapshot-*.json" | Sort-Object Name
    $totalSnapshots = $allSnapshots.Count
    $totalHealthy = 0
    $totalSevEvents = 0

    foreach ($sf in $allSnapshots) {
        $s = Get-Content $sf.FullName -Raw | ConvertFrom-Json
        if ($s.all_healthy) { $totalHealthy++ }
        $totalSevEvents += @($s.sev_events).Count
    }

    $availability = if ($totalSnapshots -gt 0) { [math]::Round(($totalHealthy / $totalSnapshots) * 100, 2) } else { 0 }

    $checkpoint = @{
        checkpoint_number = $CheckpointNum
        timestamp = Get-Date -Format "o"
        elapsed_hours = $snap.elapsed_hours
        cumulative = @{
            total_snapshots = $totalSnapshots
            healthy_snapshots = $totalHealthy
            availability_percent = $availability
            total_sev_events = $totalSevEvents
        }
        current_snapshot = $snap
    }

    $cpFile = Join-Path $CheckpointDir "checkpoint-$("{0:D3}" -f $CheckpointNum)-$stamp.json"
    $checkpoint | ConvertTo-Json -Depth 5 | Out-File -FilePath $cpFile -Encoding UTF8

    Log "Checkpoint ${CheckpointNum}: availability=${availability}%, snapshots=$totalSnapshots, sev_events=$totalSevEvents" "SUMMARY"

    return $checkpoint
}

# ============================================================================
# MAIN LOOP
# ============================================================================

$SoakEnd = (Get-Date).AddHours($DurationHours)
$SnapshotCount = 0
$CheckpointCount = 0
$LastCheckpoint = Get-Date
$Aborted = $false

Log "=== SOAK MONITOR STARTED ===" "HEADER"
Log "Duration: ${DurationHours}h, Snapshots every ${SnapshotIntervalMinutes}m, Checkpoints every ${CheckpointIntervalMinutes}m" "INFO"
Log "End time: $($SoakEnd.ToString('yyyy-MM-dd HH:mm:ss'))" "INFO"
Log "Baseline: $BaselineFile" "INFO"

while ((Get-Date) -lt $SoakEnd) {
    $SnapshotCount++

    # Every checkpoint interval, write a checkpoint instead of a plain snapshot
    $minutesSinceCheckpoint = ((Get-Date) - $LastCheckpoint).TotalMinutes
    if ($minutesSinceCheckpoint -ge $CheckpointIntervalMinutes) {
        $CheckpointCount++
        $cp = Write-Checkpoint -CheckpointNum $CheckpointCount
        $LastCheckpoint = Get-Date

        # Abort check
        if ($cp.cumulative.total_sev_events -gt 0) {
            Log "SOAK ABORTED: Sev events detected at checkpoint $CheckpointCount" "FAIL"
            $Aborted = $true
            break
        }
    } else {
        # Regular snapshot
        $snap = Write-Snapshot -Tag "snapshot-$SnapshotCount"

        # Immediate abort on Sev-1
        $sev1 = @($snap.sev_events | Where-Object { $_.Severity -eq "SEV-1" })
        if ($sev1.Count -gt 0) {
            Log "SOAK ABORTED: Sev-1 event detected" "FAIL"
            $Aborted = $true
            break
        }

        # Immediate abort on Sev-2
        $sev2 = @($snap.sev_events | Where-Object { $_.Severity -eq "SEV-2" })
        if ($sev2.Count -gt 0) {
            Log "SOAK ABORTED: Sev-2 event detected" "FAIL"
            $Aborted = $true
            break
        }
    }

    # T+24h interim review marker
    $elapsed = ((Get-Date) - [datetime]$Baseline.start_time).TotalHours
    if ($elapsed -ge 24 -and $elapsed -lt 24.3 -and -not (Test-Path (Join-Path $SoakDir "interim-review-done.txt"))) {
        Log "=== T+24h INTERIM REVIEW POINT ===" "HEADER"
        Log "Trigger manual waiver revalidation. Mark with interim-review-done.txt when complete." "INFO"
        "T+24h interim review reached at $(Get-Date -Format 'o')" | Out-File -FilePath (Join-Path $SoakDir "interim-review-done.txt") -Encoding UTF8
    }

    Start-Sleep -Seconds ($SnapshotIntervalMinutes * 60)
}

# ============================================================================
# SOAK COMPLETE
# ============================================================================

if ($Aborted) {
    Log "=== SOAK FAILED ===" "FAIL"
    Log "Re-enter Gate 1." "FAIL"
    $exitStatus = "ABORTED"
} else {
    Log "=== SOAK WINDOW COMPLETE ===" "HEADER"
    Log "Run soak-finalize.ps1 to capture T+48h hashes and generate SOAK_REPORT.md" "INFO"
    $exitStatus = "COMPLETED"
}

# Write soak status
@{
    status = $exitStatus
    end_time = Get-Date -Format "o"
    total_snapshots = $SnapshotCount
    total_checkpoints = $CheckpointCount
    aborted = $Aborted
} | ConvertTo-Json | Out-File -FilePath (Join-Path $SoakDir "soak-status.json") -Encoding UTF8

exit $(if ($Aborted) { 1 } else { 0 })
