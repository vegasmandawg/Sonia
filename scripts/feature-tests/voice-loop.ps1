<#
.SYNOPSIS
Feature test runner for voice-loop-hardening.

.DESCRIPTION
Runs all voice loop hardening unit tests and reports results.
Used by qualify-change.ps1 -FeatureTest parameter.

Exit code 0 = all tests passed.
Non-zero   = at least one test failed.
#>

Set-StrictMode -Version Latest

$pythonExe = 'S:\envs\sonia-core\python.exe'
$testDir = 'S:\tests\pipecat'

Write-Host "`nVoice Loop Hardening - Feature Tests" -ForegroundColor Cyan
Write-Host "=====================================" -ForegroundColor Cyan

$allPassed = $true
$testFiles = @(
    "test_turn_state_machine.py",
    "test_interrupt_bargein.py",
    "test_watchdog_recovery.py"
)

foreach ($tf in $testFiles) {
    $testPath = Join-Path $testDir $tf
    Write-Host "`n--- $tf ---" -ForegroundColor Yellow

    if (-not (Test-Path $testPath)) {
        Write-Host "[FAIL] Test file not found: $testPath" -ForegroundColor Red
        $allPassed = $false
        continue
    }

    # Run with Continue so stderr from Python logging doesn't terminate
    $ErrorActionPreference = "Continue"
    $output = & $pythonExe -X utf8 $testPath 2>&1
    $exitCode = $LASTEXITCODE
    $ErrorActionPreference = "Stop"

    # Display output — filter log noise from stderr
    foreach ($line in $output) {
        $text = "$line"
        if ($text -match "^PASS:") {
            Write-Host "  $text" -ForegroundColor Green
        } elseif ($text -match "^FAIL:") {
            Write-Host "  $text" -ForegroundColor Red
        } elseif ($text -match "^Total:") {
            Write-Host "  $text"
        }
        # Skip all other output (log noise from stderr)
    }

    if ($exitCode -ne 0) {
        Write-Host "[FAIL] $tf exited with code $exitCode" -ForegroundColor Red
        $allPassed = $false
    } else {
        Write-Host "[OK] $tf" -ForegroundColor Green
    }
}

Write-Host "`n=====================================" -ForegroundColor Cyan
if ($allPassed) {
    Write-Host "VOICE LOOP FEATURE TESTS: ALL PASSED" -ForegroundColor Green
    exit 0
} else {
    Write-Host "VOICE LOOP FEATURE TESTS: FAILED" -ForegroundColor Red
    exit 1
}
