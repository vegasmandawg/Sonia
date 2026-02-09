<#
.SYNOPSIS
Feature tests for Action Safety Layer.

.DESCRIPTION
Runs two test suites:
  1. test_policy_engine.py   (S1-S15)
  2. test_confirmation_flow.py (F1-F17)
Exits 0 on all-pass, 1 on any failure.

Compatible with qualify-change.ps1 -FeatureTest.
#>

Set-StrictMode -Version Latest

$py = 'S:\envs\sonia-core\python.exe'
$testDir = 'S:\tests\safety'
$suites = @(
    'test_policy_engine.py',
    'test_confirmation_flow.py'
)

$totalPass = 0
$totalFail = 0
$allOk = $true

Write-Host "`nAction Safety Layer - Feature Tests" -ForegroundColor Cyan
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
