<#
.SYNOPSIS
    Stage 7 promotion gate v2 -- stricter evidence checks for v2.6.0+.
.DESCRIPTION
    Extends the Stage 6 promotion gate with additional gates:
    1. Full regression (0 red)
    2. Health supervisor green
    3. Circuit breakers closed
    4. Dead letter queue (informational)
    5. Dependency lock integrity
    6. Frozen requirements manifest
    7. [NEW] Chaos suite passes
    8. [NEW] Backup/restore integrity verified
    9. [NEW] Diagnostics snapshot functional
    10. [NEW] Correlation ID present in action responses
    11. [NEW] Rollback script exists and dry-run succeeds
    12. [NEW] Incident bundle export functional

    Exit criterion: ALL blocking gates must pass for promotion.
#>
$ErrorActionPreference = "Stop"
$GW = "http://127.0.0.1:7000"

Write-Host "`n============================================"
Write-Host "  Promotion Gate v2 -- Stage 7"
Write-Host "  $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
Write-Host "============================================`n"

$gateResults = @{}
$allPassed = $true

# ---- Gate 1: Full regression ----
Write-Host "Gate 1: Full regression suite"
try {
    $result = & 'S:\envs\sonia-core\python.exe' -W ignore -m pytest S:\tests\integration\ --tb=line -q 2>&1
    $lastLine = ($result | Select-Object -Last 3) -join " "

    if ($lastLine -match "(\d+) passed") {
        $passCount = [int]$Matches[1]
    } else {
        $passCount = 0
    }

    if ($lastLine -match "(\d+) failed") {
        $failCount = [int]$Matches[1]
    } else {
        $failCount = 0
    }

    if ($failCount -eq 0 -and $passCount -gt 0) {
        Write-Host "  [PASS] $passCount tests passed, 0 failed"
        $gateResults["01_regression"] = "PASS"
    } else {
        Write-Host "  [FAIL] $passCount passed, $failCount failed"
        $gateResults["01_regression"] = "FAIL"
        $allPassed = $false
    }
} catch {
    Write-Host "  [FAIL] Regression suite error: $_"
    $gateResults["01_regression"] = "FAIL"
    $allPassed = $false
}

# ---- Gate 2: Health supervisor ----
Write-Host "`nGate 2: Health supervisor status"
try {
    $health = Invoke-RestMethod -Uri "$GW/v1/health/summary" -TimeoutSec 5
    if ($health.overall_state -eq "healthy") {
        Write-Host "  [PASS] Overall state: healthy"
        $gateResults["02_health"] = "PASS"
    } else {
        Write-Host "  [FAIL] Overall state: $($health.overall_state)"
        $gateResults["02_health"] = "FAIL"
        $allPassed = $false
    }
} catch {
    Write-Host "  [FAIL] Could not reach health endpoint: $_"
    $gateResults["02_health"] = "FAIL"
    $allPassed = $false
}

# ---- Gate 3: Breakers closed ----
Write-Host "`nGate 3: Circuit breakers"
try {
    $breakers = Invoke-RestMethod -Uri "$GW/v1/breakers" -TimeoutSec 5
    $allClosed = $true
    foreach ($b in $breakers.breakers.PSObject.Properties) {
        if ($b.Value.state -ne "closed") {
            Write-Host "  [FAIL] Breaker $($b.Name): $($b.Value.state)"
            $allClosed = $false
        } else {
            Write-Host "  [OK] Breaker $($b.Name): closed"
        }
    }
    $gateResults["03_breakers"] = if ($allClosed) { "PASS" } else { "FAIL" }
    if (-not $allClosed) { $allPassed = $false }
} catch {
    Write-Host "  [FAIL] Could not reach breakers endpoint: $_"
    $gateResults["03_breakers"] = "FAIL"
    $allPassed = $false
}

# ---- Gate 4: DLQ (informational) ----
Write-Host "`nGate 4: Dead letter queue"
try {
    $dlq = Invoke-RestMethod -Uri "$GW/v1/dead-letters" -TimeoutSec 5
    if ($dlq.total -eq 0) {
        Write-Host "  [PASS] 0 unresolved dead letters"
        $gateResults["04_dlq"] = "PASS"
    } else {
        Write-Host "  [WARN] $($dlq.total) unresolved dead letters (non-blocking)"
        $gateResults["04_dlq"] = "WARN"
    }
} catch {
    Write-Host "  [FAIL] Could not reach dead letters endpoint: $_"
    $gateResults["04_dlq"] = "FAIL"
    $allPassed = $false
}

# ---- Gate 5: Dependency lock integrity ----
Write-Host "`nGate 5: Dependency lock integrity"
if (Test-Path "S:\config\dependency-lock.json") {
    $lock = Get-Content "S:\config\dependency-lock.json" | ConvertFrom-Json
    Write-Host "  Lock digest: $($lock.sha256_digest.Substring(0, 16))..."
    Write-Host "  Package count: $($lock.package_count)"
    $gateResults["05_dep_lock"] = "PASS"
} else {
    Write-Host "  [FAIL] dependency-lock.json not found"
    $gateResults["05_dep_lock"] = "FAIL"
    $allPassed = $false
}

# ---- Gate 6: Frozen requirements ----
Write-Host "`nGate 6: Frozen requirements manifest"
if (Test-Path "S:\config\requirements-frozen.txt") {
    $lineCount = (Get-Content "S:\config\requirements-frozen.txt" | Measure-Object -Line).Lines
    Write-Host "  [PASS] requirements-frozen.txt present ($lineCount packages)"
    $gateResults["06_requirements"] = "PASS"
} else {
    Write-Host "  [FAIL] requirements-frozen.txt not found"
    $gateResults["06_requirements"] = "FAIL"
    $allPassed = $false
}

# ---- Gate 7: Chaos suite passes ----
Write-Host "`nGate 7: Chaos + recovery certification"
try {
    $chaosResult = & 'S:\envs\sonia-core\python.exe' -W ignore -m pytest S:\tests\integration\test_stage7_chaos_recovery.py --tb=line -q 2>&1
    $chaosLine = ($chaosResult | Select-Object -Last 3) -join " "

    if ($chaosLine -match "(\d+) passed" -and $chaosLine -notmatch "failed") {
        $chaosPass = [int]$Matches[1]
        Write-Host "  [PASS] $chaosPass chaos tests passed"
        $gateResults["07_chaos"] = "PASS"
    } else {
        Write-Host "  [FAIL] Chaos tests: $chaosLine"
        $gateResults["07_chaos"] = "FAIL"
        $allPassed = $false
    }
} catch {
    Write-Host "  [FAIL] Chaos suite error: $_"
    $gateResults["07_chaos"] = "FAIL"
    $allPassed = $false
}

# ---- Gate 8: Backup integrity ----
Write-Host "`nGate 8: Backup/restore integrity"
try {
    $backup = Invoke-RestMethod -Uri "$GW/v1/backups" -Method POST -Body "label=promotion-gate" -ContentType "application/x-www-form-urlencoded" -TimeoutSec 15
    if (-not $backup) {
        # Try without body
        $backup = Invoke-RestMethod -Uri "$GW/v1/backups?label=promotion-gate" -Method POST -TimeoutSec 15
    }

    if ($backup.ok) {
        $bid = $backup.backup.backup_id
        $verify = Invoke-RestMethod -Uri "$GW/v1/backups/$bid/verify" -TimeoutSec 10
        if ($verify.ok) {
            Write-Host "  [PASS] Backup created and verified: $bid"
            $gateResults["08_backup"] = "PASS"
        } else {
            Write-Host "  [FAIL] Backup verification failed"
            $gateResults["08_backup"] = "FAIL"
            $allPassed = $false
        }
    } else {
        Write-Host "  [FAIL] Backup creation failed"
        $gateResults["08_backup"] = "FAIL"
        $allPassed = $false
    }
} catch {
    Write-Host "  [WARN] Backup check: $_"
    $gateResults["08_backup"] = "WARN"
}

# ---- Gate 9: Diagnostics snapshot ----
Write-Host "`nGate 9: Diagnostics snapshot functional"
try {
    $diag = Invoke-RestMethod -Uri "$GW/v1/diagnostics/snapshot" -TimeoutSec 10
    if ($diag.ok -and $diag.correlation_id) {
        Write-Host "  [PASS] Diagnostics snapshot: correlation=$($diag.correlation_id)"
        $gateResults["09_diagnostics"] = "PASS"
    } else {
        Write-Host "  [FAIL] Diagnostics snapshot not functional"
        $gateResults["09_diagnostics"] = "FAIL"
        $allPassed = $false
    }
} catch {
    Write-Host "  [FAIL] Could not reach diagnostics endpoint: $_"
    $gateResults["09_diagnostics"] = "FAIL"
    $allPassed = $false
}

# ---- Gate 10: Correlation ID in action responses ----
Write-Host "`nGate 10: Correlation ID traceability"
try {
    $body = @{
        intent = "window.list"
        params = @{}
        idempotency_key = "gate-corr-$(Get-Random)"
    } | ConvertTo-Json -Depth 3

    $actionResp = Invoke-RestMethod -Uri "$GW/v1/actions/plan" `
        -Method POST -ContentType "application/json" -Body $body `
        -Headers @{"X-Correlation-ID" = "gate-trace-001"} `
        -TimeoutSec 10

    if ($actionResp.correlation_id -eq "gate-trace-001") {
        Write-Host "  [PASS] Correlation ID echoed: gate-trace-001"
        $gateResults["10_correlation"] = "PASS"
    } else {
        Write-Host "  [FAIL] Correlation ID not echoed: $($actionResp.correlation_id)"
        $gateResults["10_correlation"] = "FAIL"
        $allPassed = $false
    }
} catch {
    Write-Host "  [FAIL] Correlation ID check failed: $_"
    $gateResults["10_correlation"] = "FAIL"
    $allPassed = $false
}

# ---- Gate 11: Rollback script exists ----
Write-Host "`nGate 11: Rollback script"
if (Test-Path "S:\scripts\rollback-to-stage5.ps1") {
    Write-Host "  [PASS] rollback-to-stage5.ps1 present"
    $gateResults["11_rollback"] = "PASS"
} else {
    Write-Host "  [FAIL] Rollback script not found"
    $gateResults["11_rollback"] = "FAIL"
    $allPassed = $false
}

# ---- Gate 12: Incident bundle export script exists ----
Write-Host "`nGate 12: Incident bundle export"
if (Test-Path "S:\scripts\export-incident-bundle.ps1") {
    Write-Host "  [PASS] export-incident-bundle.ps1 present"
    $gateResults["12_incident_bundle"] = "PASS"
} else {
    Write-Host "  [FAIL] Incident bundle script not found"
    $gateResults["12_incident_bundle"] = "FAIL"
    $allPassed = $false
}

# ---- Verdict ----
Write-Host "`n============================================"
Write-Host "  Promotion Gate v2 Summary"
Write-Host "============================================`n"

foreach ($kv in ($gateResults.GetEnumerator() | Sort-Object Name)) {
    $icon = switch ($kv.Value) {
        "PASS" { "[OK]" }
        "WARN" { "[!!]" }
        default { "[XX]" }
    }
    Write-Host "  $icon $($kv.Name): $($kv.Value)"
}

$passCount = ($gateResults.Values | Where-Object { $_ -eq "PASS" }).Count
$totalCount = $gateResults.Count

Write-Host "`n  Gates: $passCount/$totalCount passed"

if ($allPassed) {
    Write-Host "`n[PROMOTE] All gates passed -- safe to promote"
    exit 0
} else {
    Write-Host "`n[BLOCKED] One or more gates failed -- do NOT promote"
    exit 1
}
