# Verify Python and execute Gate 1
param(
    [int]$CycleCount = 10,
    [int]$HealthCheckDurationMinutes = 30,
    [int]$StartupTimeoutSeconds = 90
)

$pythonPath = "S:\tools\python\python.exe"

Write-Host ""
Write-Host "=========================================="
Write-Host "Python Verification & Gate 1 Execution"
Write-Host "=========================================="
Write-Host "Timestamp: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss.fff')"
Write-Host ""

# Verify Python
Write-Host "[VERIFY] Testing Python installation..."
if (-not (Test-Path $pythonPath)) {
    Write-Host "✗ Python not found at: $pythonPath"
    exit 1
}

Write-Host "✓ Python executable found"
$version = & $pythonPath --version 2>&1
$exitCode = $LASTEXITCODE

if ($exitCode -ne 0) {
    Write-Host "✗ Python test failed"
    exit 1
}

Write-Host "✓ Python working: $version"
Write-Host ""

# Set deterministic environment
Write-Host "[SETUP] Setting deterministic environment..."
$env:PYTHONHASHSEED = "0"
$env:SONIA_TEST_MODE = "deterministic"
Write-Host "✓ PYTHONHASHSEED=0"
Write-Host "✓ SONIA_TEST_MODE=deterministic"
Write-Host ""

# Execute Gate 1
Write-Host "[GATE 1] Executing Go/No-Go Gate..."
Write-Host "Parameters:"
Write-Host "  CycleCount: $CycleCount"
Write-Host "  HealthCheckDurationMinutes: $HealthCheckDurationMinutes"
Write-Host "  StartupTimeoutSeconds: $StartupTimeoutSeconds"
Write-Host ""

$gateScript = "S:\scripts\testing\phase3-go-no-go.ps1"
if (-not (Test-Path $gateScript)) {
    Write-Host "✗ Gate script not found: $gateScript"
    exit 1
}

Write-Host "Executing: $gateScript"
Write-Host ""

& $gateScript -CycleCount $CycleCount -HealthCheckDurationMinutes $HealthCheckDurationMinutes -StartupTimeoutSeconds $StartupTimeoutSeconds
$gateExitCode = $LASTEXITCODE

Write-Host ""
Write-Host "=========================================="
Write-Host "Gate 1 Result: Exit Code $gateExitCode"
Write-Host "=========================================="

if ($gateExitCode -eq 0) {
    Write-Host "✓ GATE 1 PASSED - Proceeding to Gate 2"
} else {
    Write-Host "✗ GATE 1 FAILED - Review logs and errors"
}

exit $gateExitCode
