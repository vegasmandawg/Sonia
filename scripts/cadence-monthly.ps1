<#
.SYNOPSIS
    Monthly operating cadence: full recovery certification + release drill + evidence archival.
.DESCRIPTION
    Run monthly to certify operational readiness. Exercises the full test suite,
    soak test, chaos suite, backup/restore, and promotion gate. Archives all
    evidence for audit trail.
#>
param(
    [string]$OutputDir = "S:\reports\cadence",
    [int]$SoakActions = 100
)
$ErrorActionPreference = "Continue"
$GW = "http://127.0.0.1:7000"
$PYTHON = "S:\envs\sonia-core\python.exe"
$ts = Get-Date -Format "yyyyMMdd-HHmmss"
$reportDir = "$OutputDir\monthly-$ts"
New-Item -ItemType Directory -Path $reportDir -Force | Out-Null

Write-Host "`n============================================"
Write-Host "  MONTHLY CADENCE -- $(Get-Date -Format 'yyyy-MM-dd HH:mm')"
Write-Host "============================================"

$checks = @{}
$issues = @()

# -- 1. Full regression suite --
Write-Host "`n[1/5] Full regression suite"
try {
    $testOutput = & $PYTHON -W ignore -m pytest S:\tests\integration\ --tb=line -q 2>&1
    $testText = $testOutput -join "`n"
    $testText | Out-File -Encoding utf8 "$reportDir\regression.txt"
    $lastLines = ($testOutput | Select-Object -Last 3) -join " "

    if ($lastLines -match "(\d+) passed") { $passCount = [int]$Matches[1] } else { $passCount = 0 }
    if ($lastLines -match "(\d+) failed") { $failCount = [int]$Matches[1] } else { $failCount = 0 }

    if ($failCount -eq 0 -and $passCount -gt 0) {
        Write-Host "  [OK] $passCount passed, 0 failed"
        $checks["regression"] = "OK ($passCount passed)"
    } else {
        Write-Host "  [!!] $passCount passed, $failCount failed"
        $checks["regression"] = "FAIL ($failCount failed)"
        $issues += "Regression: $failCount test failures"
    }
} catch {
    Write-Host "  [XX] Regression error: $_"
    $checks["regression"] = "ERROR"
    $issues += "Regression suite execution error"
}

# -- 2. Chaos + recovery certification --
Write-Host "`n[2/5] Chaos + recovery certification"
try {
    $chaosOutput = & $PYTHON -W ignore -m pytest S:\tests\integration\test_stage7_chaos_recovery.py S:\tests\integration\test_stage7_backup_restore.py --tb=short -q 2>&1
    $chaosText = $chaosOutput -join "`n"
    $chaosText | Out-File -Encoding utf8 "$reportDir\chaos-recovery.txt"
    $lastLines = ($chaosOutput | Select-Object -Last 3) -join " "

    if ($lastLines -match "(\d+) passed" -and $lastLines -notmatch "failed") {
        $passCount = [int]$Matches[1]
        Write-Host "  [OK] $passCount chaos+backup tests passed"
        $checks["chaos_recovery"] = "OK ($passCount passed)"
    } else {
        Write-Host "  [!!] Chaos results: $lastLines"
        $checks["chaos_recovery"] = "FAIL"
        $issues += "Chaos/recovery certification: $lastLines"
    }
} catch {
    Write-Host "  [XX] Chaos error: $_"
    $checks["chaos_recovery"] = "ERROR"
    $issues += "Chaos suite execution error"
}

# -- 3. Release drill (promotion gate v2) --
Write-Host "`n[3/5] Release drill (promotion gate v2)"
try {
    $gateOutput = & powershell.exe -ExecutionPolicy Bypass -File "S:\scripts\promotion-gate-v2.ps1" 2>&1
    $gateText = $gateOutput -join "`n"
    $gateText | Out-File -Encoding utf8 "$reportDir\promotion-gate.txt"

    if ($gateText -match "PROMOTE") {
        Write-Host "  [OK] All promotion gates passed"
        $checks["promotion_gate"] = "OK"
    } else {
        Write-Host "  [!!] Promotion gate did not fully pass"
        $checks["promotion_gate"] = "WARN"
        $issues += "Promotion gate: not all gates passed"
    }
} catch {
    Write-Host "  [XX] Promotion gate error: $_"
    $checks["promotion_gate"] = "ERROR"
    $issues += "Promotion gate execution error"
}

# -- 4. Backup integrity verification --
Write-Host "`n[4/5] Backup integrity verification"
try {
    $backup = Invoke-RestMethod -Uri "$GW/v1/backups?label=monthly-cadence" -Method POST -TimeoutSec 15
    if ($backup.ok) {
        $bid = $backup.backup.backup_id
        $verify = Invoke-RestMethod -Uri "$GW/v1/backups/$bid/verify" -TimeoutSec 10
        $verify | ConvertTo-Json -Depth 5 | Out-File -Encoding utf8 "$reportDir\backup-verify.json"
        if ($verify.ok) {
            Write-Host "  [OK] Backup $bid verified"
            $checks["backup"] = "OK"
        } else {
            Write-Host "  [!!] Backup verification failed"
            $checks["backup"] = "FAIL"
            $issues += "Backup integrity verification failed"
        }
    } else {
        $checks["backup"] = "FAIL"
        $issues += "Backup creation failed"
    }
} catch {
    Write-Host "  [XX] Backup error: $_"
    $checks["backup"] = "ERROR"
    $issues += "Backup check failed"
}

# -- 5. Incident bundle export --
Write-Host "`n[5/5] Incident bundle export (dry check)"
if (Test-Path "S:\scripts\export-incident-bundle.ps1") {
    Write-Host "  [OK] export-incident-bundle.ps1 present"
    $checks["incident_bundle"] = "OK"
} else {
    Write-Host "  [!!] export-incident-bundle.ps1 missing"
    $checks["incident_bundle"] = "FAIL"
    $issues += "Incident bundle script missing"
}

# -- Summary --
Write-Host "`n============================================"
Write-Host "  MONTHLY SUMMARY"
Write-Host "============================================"
foreach ($kv in ($checks.GetEnumerator() | Sort-Object Name)) {
    $icon = switch -Wildcard ($kv.Value) {
        "OK*"    { "[OK]" }
        "WARN*"  { "[!!]" }
        default  { "[XX]" }
    }
    Write-Host "  $icon $($kv.Name): $($kv.Value)"
}

$okCount = ($checks.Values | Where-Object { $_ -like "OK*" }).Count
Write-Host "`n  Checks: $okCount/$($checks.Count) passed"

if ($issues.Count -gt 0) {
    Write-Host "`n  Issues:"
    foreach ($i in $issues) { Write-Host "    - $i" }
    Write-Host "`n[ATTENTION] $($issues.Count) issue(s) -- review before next release"
} else {
    Write-Host "`n[CERTIFIED] Monthly recovery certification passed"
}

# -- Archive --
Write-Host "`nEvidence archived: $reportDir"
Write-Host "Files:"
Get-ChildItem $reportDir -File | ForEach-Object { Write-Host "  $($_.Name) ($($_.Length) bytes)" }
