<#
.SYNOPSIS
    Weekly operating cadence: chaos mini-suite + restore dry-run + dependency CVE scan.
.DESCRIPTION
    Run weekly to verify recovery readiness and dependency health.
    Includes a subset of chaos tests, backup restore dry-run, and
    advisory dependency vulnerability scan.
#>
param(
    [string]$OutputDir = "S:\reports\cadence"
)
$ErrorActionPreference = "Continue"
$GW = "http://127.0.0.1:7000"
$PYTHON = "S:\envs\sonia-core\python.exe"
$ts = Get-Date -Format "yyyyMMdd-HHmmss"
$reportDir = "$OutputDir\weekly-$ts"
New-Item -ItemType Directory -Path $reportDir -Force | Out-Null

Write-Host "`n========================================="
Write-Host "  WEEKLY CADENCE -- $(Get-Date -Format 'yyyy-MM-dd HH:mm')"
Write-Host "========================================="

$checks = @{}
$issues = @()

# -- 1. Chaos mini-suite --
Write-Host "`n[1/3] Chaos mini-suite (Stage 7 chaos tests)"
try {
    $chaosOutput = & $PYTHON -W ignore -m pytest S:\tests\integration\test_stage7_chaos_recovery.py --tb=short -q 2>&1
    $chaosText = $chaosOutput -join "`n"
    $chaosText | Out-File -Encoding utf8 "$reportDir\chaos-results.txt"
    $lastLines = ($chaosOutput | Select-Object -Last 3) -join " "

    if ($lastLines -match "(\d+) passed" -and $lastLines -notmatch "failed") {
        $passCount = [int]$Matches[1]
        Write-Host "  [OK] $passCount chaos tests passed"
        $checks["chaos_suite"] = "OK ($passCount passed)"
    } else {
        Write-Host "  [!!] Chaos results: $lastLines"
        $checks["chaos_suite"] = "FAIL"
        $issues += "Chaos suite did not fully pass: $lastLines"
    }
} catch {
    Write-Host "  [XX] Chaos suite error: $_"
    $checks["chaos_suite"] = "ERROR"
    $issues += "Chaos suite execution error"
}

# -- 2. Backup restore dry-run --
Write-Host "`n[2/3] Backup restore dry-run"
try {
    # Create a fresh backup
    $backup = Invoke-RestMethod -Uri "$GW/v1/backups?label=weekly-cadence" -Method POST -TimeoutSec 15
    if ($backup.ok) {
        $bid = $backup.backup.backup_id
        Write-Host "  Backup created: $bid"

        # Verify integrity
        $verify = Invoke-RestMethod -Uri "$GW/v1/backups/$bid/verify" -TimeoutSec 10
        if ($verify.ok) {
            Write-Host "  [OK] Integrity verified"
        } else {
            Write-Host "  [!!] Integrity verification failed"
            $issues += "Backup integrity verification failed"
        }

        # Dry-run restore
        $restore = Invoke-RestMethod -Uri "$GW/v1/backups/$bid/restore/dlq?dry_run=true" -Method POST -TimeoutSec 10
        $restore | ConvertTo-Json -Depth 3 | Out-File -Encoding utf8 "$reportDir\restore-dryrun.json"
        if ($restore.ok -and $restore.dry_run -eq $true) {
            Write-Host "  [OK] DLQ restore dry-run validated (records: $($restore.records_to_restore))"
            $checks["backup_restore"] = "OK"
        } else {
            Write-Host "  [!!] Restore dry-run: unexpected result"
            $checks["backup_restore"] = "WARN"
        }
    } else {
        Write-Host "  [!!] Backup creation failed"
        $checks["backup_restore"] = "FAIL"
        $issues += "Backup creation failed"
    }
} catch {
    Write-Host "  [XX] Backup/restore error: $_"
    $checks["backup_restore"] = "ERROR"
    $issues += "Backup/restore check failed"
}

# -- 3. Dependency CVE scan (advisory) --
Write-Host "`n[3/3] Dependency CVE scan (advisory)"
try {
    # Use pip-audit if available, otherwise use pip check
    $auditResult = & $PYTHON -m pip_audit --requirement S:\config\requirements-frozen.txt 2>&1
    $auditText = $auditResult -join "`n"
    $auditText | Out-File -Encoding utf8 "$reportDir\cve-scan.txt"

    if ($auditText -match "No known vulnerabilities") {
        Write-Host "  [OK] No known vulnerabilities"
        $checks["cve_scan"] = "OK"
    } elseif ($auditText -match "found (\d+) vulnerabilit") {
        $vulnCount = $Matches[1]
        Write-Host "  [!!] $vulnCount vulnerabilities found (advisory -- review report)"
        $checks["cve_scan"] = "ADVISORY ($vulnCount vulns)"
        $issues += "$vulnCount dependency vulnerabilities found (advisory)"
    } else {
        # pip-audit not installed -- fall back to pip check
        Write-Host "  [INFO] pip-audit not available, falling back to pip check"
        $checkResult = & $PYTHON -m pip check 2>&1
        $checkText = $checkResult -join "`n"
        $checkText | Out-File -Encoding utf8 "$reportDir\pip-check.txt"
        if ($checkText -match "No broken requirements") {
            Write-Host "  [OK] No broken requirements (pip check)"
            $checks["cve_scan"] = "OK (pip check only)"
        } else {
            Write-Host "  [!!] pip check issues: $checkText"
            $checks["cve_scan"] = "WARN"
        }
    }
} catch {
    Write-Host "  [INFO] CVE scan: $_"
    $checks["cve_scan"] = "SKIPPED"
}

# -- Summary --
Write-Host "`n========================================="
Write-Host "  WEEKLY SUMMARY"
Write-Host "========================================="
foreach ($kv in ($checks.GetEnumerator() | Sort-Object Name)) {
    Write-Host "  $($kv.Name): $($kv.Value)"
}

if ($issues.Count -gt 0) {
    Write-Host "`n  Issues:"
    foreach ($i in $issues) { Write-Host "    - $i" }
    Write-Host "`n[ATTENTION] $($issues.Count) issue(s) found"
} else {
    Write-Host "`n[ALL CLEAR] Weekly checks passed"
}

Write-Host "`nReport: $reportDir"
