Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$env:PYTHONHASHSEED = "0"
$env:SONIA_TEST_MODE = "deterministic"

Write-Host "=== PRECHECK ==="
Write-Host "PYTHONHASHSEED: $env:PYTHONHASHSEED"
Write-Host "SONIA_TEST_MODE: $env:SONIA_TEST_MODE"

Write-Host "=== PREFLIGHT ==="
& "S:\scripts\testing\phase3-preflight.ps1"
if ($LASTEXITCODE -and $LASTEXITCODE -ne 0) {
    Write-Host "[FAIL] preflight - services not responding"
    exit 10
}

Write-Host "=== GATE 1 EXECUTION ==="
& "S:\scripts\testing\phase3-go-no-go.ps1" -CycleCount 10 -HealthCheckDurationMinutes 30 -StartupTimeoutSeconds 90
if ($LASTEXITCODE -and $LASTEXITCODE -ne 0) {
    Write-Host "[FAIL] gate1"
    exit 11
}

Write-Host "[SUCCESS] Gate 1 complete."
exit 0
