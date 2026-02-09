# Direct Gate 1 execution
$env:PYTHONHASHSEED = "0"
$env:SONIA_TEST_MODE = "deterministic"

Set-Location S:\scripts\testing

# Quick 2-cycle test with 1-minute health check
& .\phase3-gate1-execute.ps1 -CycleCount 2 -HealthCheckDurationMinutes 1 -StartupTimeoutSeconds 30
