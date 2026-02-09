<#
.SYNOPSIS
Finalize the 48-hour soak: capture T+48h hashes, run determinism spot-check, produce SOAK_REPORT.md.

.EXAMPLE
.\soak-finalize.ps1
#>

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$SoakDir = "S:\artifacts\phase3\soak"
$SnapshotDir = Join-Path $SoakDir "snapshots"
$CheckpointDir = Join-Path $SoakDir "checkpoints"

Write-Host "`n=== SOAK FINALIZATION (T+48h) ===" -ForegroundColor Cyan

# Load baseline
$Baseline = Get-Content (Join-Path $SoakDir "t0-baseline.json") -Raw | ConvertFrom-Json
$T0 = [datetime]$Baseline.start_time
$elapsed = [math]::Round(((Get-Date) - $T0).TotalHours, 2)
Write-Host "T0: $($T0.ToString('yyyy-MM-dd HH:mm:ss'))" -ForegroundColor DarkCyan
Write-Host "Now: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')" -ForegroundColor DarkCyan
Write-Host "Elapsed: ${elapsed}h" -ForegroundColor DarkCyan

# Step 1: Config hash at T+48h
Write-Host "`n--- Config Hash T+48h ---" -ForegroundColor Yellow
if (Test-Path "S:\config\sonia-config.json") {
    $configHash48 = (Get-FileHash -LiteralPath "S:\config\sonia-config.json" -Algorithm SHA256).Hash
} else {
    $configHash48 = "NOT_FOUND"
}
$configMatch = ($configHash48 -eq $Baseline.config_hash)
Write-Host "  T0:    $($Baseline.config_hash)" -ForegroundColor $(if ($configMatch) { "Green" } else { "Red" })
Write-Host "  T+48h: $configHash48" -ForegroundColor $(if ($configMatch) { "Green" } else { "Red" })
Write-Host "  Match: $configMatch" -ForegroundColor $(if ($configMatch) { "Green" } else { "Red" })

# Step 2: PID stability check
Write-Host "`n--- PID Stability ---" -ForegroundColor Yellow
$pidStable = $true
$ServiceSpec = @(
    @{ Name="api-gateway"; Port=7000; Pid="S:\state\pids\api-gateway.pid" },
    @{ Name="model-router"; Port=7010; Pid="S:\state\pids\model-router.pid" },
    @{ Name="memory-engine"; Port=7020; Pid="S:\state\pids\memory-engine.pid" },
    @{ Name="pipecat"; Port=7030; Pid="S:\state\pids\pipecat.pid" },
    @{ Name="openclaw"; Port=7040; Pid="S:\state\pids\openclaw.pid" },
    @{ Name="eva-os"; Port=7050; Pid="S:\state\pids\eva-os.pid" }
)

foreach ($svc in $ServiceSpec) {
    $currentPID = $null
    if (Test-Path $svc.Pid) {
        $currentPID = [int](Get-Content $svc.Pid -ErrorAction Stop | Select-Object -First 1)
    }
    $baselinePID = $Baseline.pids.($svc.Name)
    $match = ($currentPID -eq $baselinePID)
    if (-not $match) { $pidStable = $false }
    Write-Host "  $($svc.Name): T0=$baselinePID T+48h=$currentPID $(if ($match) { 'OK' } else { 'CHANGED' })" -ForegroundColor $(if ($match) { "Green" } else { "Red" })
}

# Step 3: Final health check
Write-Host "`n--- Final Health Check ---" -ForegroundColor Yellow
$allHealthy = $true
foreach ($svc in $ServiceSpec) {
    try {
        $resp = Invoke-WebRequest -Uri "http://127.0.0.1:$($svc.Port)/healthz" -TimeoutSec 5 -UseBasicParsing -ErrorAction Stop
        $healthy = ($resp.StatusCode -eq 200)
        if (-not $healthy) { $allHealthy = $false }
        Write-Host "  $($svc.Name): $(if ($healthy) { 'HEALTHY' } else { 'UNHEALTHY' })" -ForegroundColor $(if ($healthy) { "Green" } else { "Red" })
    } catch {
        Write-Host "  $($svc.Name): DOWN" -ForegroundColor Red
        $allHealthy = $false
    }
}

# Step 4: Determinism spot-check
Write-Host "`n--- Determinism Spot-Check ---" -ForegroundColor Yellow
$SpotRun1 = & "S:\envs\sonia-core\python.exe" -m pytest "S:\tests\integration\test_phase2_e2e.py" -v --tb=no 2>&1
$SpotSummary1 = ($SpotRun1 | Select-String "=+ .*(passed|failed).* =+$" | Select-Object -Last 1).Line
$SpotPassed1 = if ($SpotSummary1 -match '(\d+) passed') { [int]$Matches[1] } else { 0 }
$SpotFailed1 = if ($SpotSummary1 -match '(\d+) failed') { [int]$Matches[1] } else { 0 }
Write-Host "  Spot Run 1: $SpotPassed1 passed, $SpotFailed1 failed" -ForegroundColor DarkCyan

$SpotRun2 = & "S:\envs\sonia-core\python.exe" -m pytest "S:\tests\integration\test_phase2_e2e.py" -v --tb=no 2>&1
$SpotSummary2 = ($SpotRun2 | Select-String "=+ .*(passed|failed).* =+$" | Select-Object -Last 1).Line
$SpotPassed2 = if ($SpotSummary2 -match '(\d+) passed') { [int]$Matches[1] } else { 0 }
$SpotFailed2 = if ($SpotSummary2 -match '(\d+) failed') { [int]$Matches[1] } else { 0 }
Write-Host "  Spot Run 2: $SpotPassed2 passed, $SpotFailed2 failed" -ForegroundColor DarkCyan

$spotDeterministic = ($SpotPassed1 -eq $SpotPassed2 -and $SpotFailed1 -eq $SpotFailed2)
$spotMatchBaseline = ($SpotPassed1 -eq 18 -and $SpotFailed1 -eq 2)
Write-Host "  Deterministic: $spotDeterministic" -ForegroundColor $(if ($spotDeterministic) { "Green" } else { "Red" })
Write-Host "  Matches baseline (18p/2f): $spotMatchBaseline" -ForegroundColor $(if ($spotMatchBaseline) { "Green" } else { "Yellow" })

# Step 5: Compute cumulative metrics from all snapshots
Write-Host "`n--- Cumulative Metrics ---" -ForegroundColor Yellow
$allSnaps = @(Get-ChildItem $SnapshotDir -Filter "snapshot-*.json" -ErrorAction SilentlyContinue | Sort-Object Name)
$totalSnaps = $allSnaps.Count
$healthySnaps = 0
$totalSevEvents = 0

foreach ($sf in $allSnaps) {
    $s = Get-Content $sf.FullName -Raw | ConvertFrom-Json
    if ($s.all_healthy) { $healthySnaps++ }
    $totalSevEvents += @($s.sev_events).Count
}

$availability = if ($totalSnaps -gt 0) { [math]::Round(($healthySnaps / $totalSnaps) * 100, 3) } else { 0 }
Write-Host "  Total snapshots: $totalSnaps" -ForegroundColor DarkCyan
Write-Host "  Healthy snapshots: $healthySnaps" -ForegroundColor DarkCyan
Write-Host "  Availability: $availability%" -ForegroundColor $(if ($availability -ge 99.9) { "Green" } else { "Red" })
Write-Host "  Sev events: $totalSevEvents" -ForegroundColor $(if ($totalSevEvents -eq 0) { "Green" } else { "Red" })

# Step 6: Overall verdict
$soakPass = $configMatch -and $pidStable -and $allHealthy -and $spotDeterministic -and ($totalSevEvents -eq 0) -and ($availability -ge 99.9)

# Step 7: Generate SOAK_REPORT.md
$report = @"
# 48-Hour Soak Report

## Verdict: $(if ($soakPass) { "PASSED" } else { "FAILED" })

**T0:** $($T0.ToString('yyyy-MM-dd HH:mm:ss'))
**T+48h:** $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')
**Elapsed:** ${elapsed}h
**RC:** RC-1 (build tag 20260208_164811)

---

## Config Integrity

| Checkpoint | Hash | Match |
|------------|------|-------|
| T0 | ``$($Baseline.config_hash)`` | baseline |
| T+48h | ``$configHash48`` | $(if ($configMatch) { "YES" } else { "NO - DRIFT DETECTED" }) |

---

## Availability

| Metric | Value | Threshold | Verdict |
|--------|-------|-----------|---------|
| Total snapshots | $totalSnaps | - | - |
| Healthy snapshots | $healthySnaps | - | - |
| Availability | $availability% | >= 99.9% | $(if ($availability -ge 99.9) { "PASS" } else { "FAIL" }) |
| Sev-1 events | $(if ($totalSevEvents -eq 0) { "0" } else { "$totalSevEvents" }) | 0 | $(if ($totalSevEvents -eq 0) { "PASS" } else { "FAIL" }) |
| Sev-2 events | $(if ($totalSevEvents -eq 0) { "0" } else { "$totalSevEvents" }) | 0 | $(if ($totalSevEvents -eq 0) { "PASS" } else { "FAIL" }) |

---

## Process Stability

| Service | T0 PID | T+48h PID | Stable |
|---------|--------|-----------|--------|
$(foreach ($svc in $ServiceSpec) {
    $bp = $Baseline.pids.($svc.Name)
    $cp = if (Test-Path $svc.Pid) { [int](Get-Content $svc.Pid | Select-Object -First 1) } else { "N/A" }
    "| $($svc.Name) | $bp | $cp | $(if ($bp -eq $cp) { 'YES' } else { 'NO' }) |`n"
})

**Restart count:** $(if ($pidStable) { "0 (all PIDs stable)" } else { "RESTARTS DETECTED" })

---

## Determinism Spot-Check (T+48h)

| Run | Passed | Failed | Deterministic | Matches Baseline |
|-----|--------|--------|---------------|------------------|
| Spot Run 1 | $SpotPassed1 | $SpotFailed1 | - | $(if ($SpotPassed1 -eq 18 -and $SpotFailed1 -eq 2) { "YES" } else { "NO" }) |
| Spot Run 2 | $SpotPassed2 | $SpotFailed2 | $(if ($spotDeterministic) { "YES" } else { "NO" }) | $(if ($SpotPassed2 -eq 18 -and $SpotFailed2 -eq 2) { "YES" } else { "NO" }) |

**Baseline:** 18 passed, 2 failed (from Gate 2B)

---

## Soak Verdict

| Check | Result |
|-------|--------|
| Config hash T0 == T+48h | $(if ($configMatch) { "PASS" } else { "FAIL" }) |
| All PIDs stable | $(if ($pidStable) { "PASS" } else { "FAIL" }) |
| All services healthy at T+48h | $(if ($allHealthy) { "PASS" } else { "FAIL" }) |
| Availability >= 99.9% | $(if ($availability -ge 99.9) { "PASS ($availability%)" } else { "FAIL ($availability%)" }) |
| Zero Sev-1/Sev-2 events | $(if ($totalSevEvents -eq 0) { "PASS" } else { "FAIL ($totalSevEvents events)" }) |
| Determinism spot-check | $(if ($spotDeterministic) { "PASS" } else { "FAIL" }) |
| **Overall** | **$(if ($soakPass) { "PASS" } else { "FAIL" })** |

---

## Next Steps

$(if ($soakPass) {
"1. Security hardening validation
2. Durability/restore validation
3. Final release ceremony with immutable artifact pack + signatures"
} else {
"1. Investigate failure root cause
2. Re-enter Gate 1 from scratch
3. Re-run full gate suite after fix"
})
"@

$reportFile = Join-Path $SoakDir "SOAK_REPORT.md"
$report | Out-File -FilePath $reportFile -Encoding UTF8

Write-Host "`n=== SOAK REPORT GENERATED ===" -ForegroundColor Cyan
Write-Host "Report: $reportFile" -ForegroundColor White
Write-Host "Verdict: $(if ($soakPass) { 'PASSED' } else { 'FAILED' })" -ForegroundColor $(if ($soakPass) { "Green" } else { "Red" })

exit $(if ($soakPass) { 0 } else { 1 })
