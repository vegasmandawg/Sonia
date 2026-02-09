# Direct Gate 1 execution with explicit error handling
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$env:PYTHONHASHSEED = "0"
$env:SONIA_TEST_MODE = "deterministic"

Write-Host "Gate 1 Starting..." -ForegroundColor Cyan

try {
    Set-Location S:\scripts\testing
    
    Write-Host "Executing phase3-go-no-go.ps1 with 10 cycles..." -ForegroundColor Yellow
    
    & .\phase3-go-no-go.ps1 -CycleCount 10 -HealthCheckDurationMinutes 30 -StartupTimeoutSeconds 90
    
    $exitCode = $LASTEXITCODE
    Write-Host "Gate 1 completed with exit code: $exitCode" -ForegroundColor Green
    
    if ($exitCode -ne 0) {
        Write-Host "Gate 1 FAILED" -ForegroundColor Red
        exit $exitCode
    }
    
    Write-Host "Gate 1 PASSED" -ForegroundColor Green
    exit 0
}
catch {
    Write-Host "ERROR: $_" -ForegroundColor Red
    Write-Host $_.ScriptStackTrace -ForegroundColor Red
    exit 1
}
