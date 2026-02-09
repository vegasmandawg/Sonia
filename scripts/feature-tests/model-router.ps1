<#
.SYNOPSIS
Feature tests for Model Router Policy Profiles.

.DESCRIPTION
Runs four test suites:
  1. test_profile_selection.py   (PS1-PS12)
  2. test_fallback_matrix.py     (FM1-FM10)
  3. test_budget_guard.py        (BG1-BG10)
  4. test_health_quarantine.py   (HQ1-HQ12)
Exits 0 on all-pass, 1 on any failure.

Compatible with qualify-change.ps1 -FeatureTest.
#>

Set-StrictMode -Version Latest

$py = 'S:\envs\sonia-core\python.exe'
$testDir = 'S:\tests\model_router'
$suites = @(
    'test_profile_selection.py',
    'test_fallback_matrix.py',
    'test_budget_guard.py',
    'test_health_quarantine.py'
)

$totalPass = 0
$totalFail = 0
$allOk = $true

Write-Host "`nModel Router Policy Profiles - Feature Tests" -ForegroundColor Cyan
Write-Host ("=" * 50) -ForegroundColor Cyan

foreach ($suite in $suites) {
    $testPath = Join-Path $testDir $suite
    Write-Host "`nRunning: $suite" -ForegroundColor Yellow

    $savedPref = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'

    $output = & $py $testPath 2>&1 | ForEach-Object { $_.ToString() }

    $ErrorActionPreference = $savedPref

    $suitePass = 0
    $suiteFail = 0

    foreach ($line in $output) {
        Write-Host $line
        if ($line -match '\[PASS\]') { $suitePass++ }
        if ($line -match '\[FAIL\]') { $suiteFail++ }
    }

    $totalPass += $suitePass
    $totalFail += $suiteFail

    if ($suiteFail -gt 0) {
        Write-Host "[FAIL] $suite : $suiteFail failures" -ForegroundColor Red
        $allOk = $false
    } else {
        Write-Host "[OK] $suite : $suitePass passed" -ForegroundColor Green
    }
}

Write-Host ("`n" + "=" * 50) -ForegroundColor Cyan
Write-Host "Total: $totalPass passed, $totalFail failed" -ForegroundColor $(if ($allOk) { "Green" } else { "Red" })

if (-not $allOk) {
    exit 1
}
exit 0
