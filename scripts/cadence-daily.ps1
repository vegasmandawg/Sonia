<#
.SYNOPSIS
    Daily operating cadence: health snapshot + error budget + breaker anomaly scan.
.DESCRIPTION
    Run every day to verify steady-state health. Outputs a single-page report
    suitable for operator review. Non-destructive, read-only checks.
#>
param(
    [string]$OutputDir = "S:\reports\cadence"
)
$ErrorActionPreference = "Continue"
$GW = "http://127.0.0.1:7000"
$ts = Get-Date -Format "yyyyMMdd-HHmmss"
$reportDir = "$OutputDir\daily-$ts"
New-Item -ItemType Directory -Path $reportDir -Force | Out-Null

Write-Host "`n========================================="
Write-Host "  DAILY CADENCE -- $(Get-Date -Format 'yyyy-MM-dd HH:mm')"
Write-Host "========================================="

$checks = @{}
$issues = @()

# -- 1. Service health snapshot --
Write-Host "`n[1/4] Health snapshot"
try {
    $health = Invoke-RestMethod -Uri "$GW/v1/health/summary" -TimeoutSec 5
    $health | ConvertTo-Json -Depth 5 | Out-File -Encoding utf8 "$reportDir\health.json"
    if ($health.overall_state -eq "healthy") {
        Write-Host "  [OK] Overall: healthy"
        $checks["health"] = "OK"
    } else {
        Write-Host "  [!!] Overall: $($health.overall_state)"
        $checks["health"] = "DEGRADED"
        $issues += "Health supervisor reports: $($health.overall_state)"
    }
} catch {
    Write-Host "  [XX] Gateway unreachable: $_"
    $checks["health"] = "UNREACHABLE"
    $issues += "Gateway unreachable: $_"
}

# -- 2. Error budget check (DLQ unresolved count) --
Write-Host "`n[2/4] Error budget (DLQ)"
try {
    $dlq = Invoke-RestMethod -Uri "$GW/v1/dead-letters" -TimeoutSec 5
    $dlq | ConvertTo-Json -Depth 3 | Out-File -Encoding utf8 "$reportDir\dlq.json"
    Write-Host "  Unresolved dead letters: $($dlq.total)"
    if ($dlq.total -eq 0) {
        $checks["error_budget"] = "OK"
    } else {
        $checks["error_budget"] = "WARN ($($dlq.total) unresolved)"
        $issues += "$($dlq.total) unresolved dead letters in DLQ"
    }
} catch {
    Write-Host "  [XX] DLQ check failed: $_"
    $checks["error_budget"] = "FAIL"
    $issues += "DLQ endpoint unreachable"
}

# -- 3. Breaker anomaly scan --
Write-Host "`n[3/4] Breaker anomaly scan"
try {
    $breakers = Invoke-RestMethod -Uri "$GW/v1/breakers" -TimeoutSec 5
    $metrics = Invoke-RestMethod -Uri "$GW/v1/breakers/metrics?last_n=50" -TimeoutSec 5
    $breakers | ConvertTo-Json -Depth 5 | Out-File -Encoding utf8 "$reportDir\breakers.json"
    $metrics | ConvertTo-Json -Depth 5 | Out-File -Encoding utf8 "$reportDir\breaker-metrics.json"

    $anomalies = @()
    foreach ($b in $breakers.breakers.PSObject.Properties) {
        $state = $b.Value.state
        if ($state -ne "closed") {
            $anomalies += "$($b.Name): $state"
        }
    }

    if ($anomalies.Count -eq 0) {
        Write-Host "  [OK] All breakers closed"
        $checks["breakers"] = "OK"
    } else {
        foreach ($a in $anomalies) { Write-Host "  [!!] $a" }
        $checks["breakers"] = "ANOMALY"
        $issues += "Breaker anomalies: $($anomalies -join ', ')"
    }
} catch {
    Write-Host "  [XX] Breaker check failed: $_"
    $checks["breakers"] = "FAIL"
    $issues += "Breaker endpoint unreachable"
}

# -- 4. Diagnostics snapshot --
Write-Host "`n[4/4] Diagnostics snapshot"
try {
    $diag = Invoke-RestMethod -Uri "$GW/v1/diagnostics/snapshot?last_n=20" -TimeoutSec 10
    $diag | ConvertTo-Json -Depth 5 | Out-File -Encoding utf8 "$reportDir\diagnostics.json"
    Write-Host "  [OK] Snapshot captured (correlation: $($diag.correlation_id))"
    $checks["diagnostics"] = "OK"
} catch {
    Write-Host "  [XX] Diagnostics failed: $_"
    $checks["diagnostics"] = "FAIL"
    $issues += "Diagnostics endpoint failed"
}

# -- Summary --
Write-Host "`n========================================="
Write-Host "  DAILY SUMMARY"
Write-Host "========================================="
foreach ($kv in ($checks.GetEnumerator() | Sort-Object Name)) {
    Write-Host "  $($kv.Name): $($kv.Value)"
}

if ($issues.Count -gt 0) {
    Write-Host "`n  Issues requiring attention:"
    foreach ($i in $issues) { Write-Host "    - $i" }
    Write-Host "`n[ATTENTION] $($issues.Count) issue(s) found"
} else {
    Write-Host "`n[ALL CLEAR] No issues detected"
}

Write-Host "`nReport: $reportDir"
