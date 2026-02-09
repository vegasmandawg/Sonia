# Phase 3: Execute Gate 1 with Python Environment Setup
# This script installs Python via Miniconda and immediately runs Gate 1

param(
    [int]$CycleCount = 10,
    [int]$HealthCheckDurationMinutes = 30,
    [int]$StartupTimeoutSeconds = 90
)

# Set deterministic environment
$env:PYTHONHASHSEED = "0"
$env:SONIA_TEST_MODE = "deterministic"

Write-Host "================================"
Write-Host "PHASE 3: Gate 1 Execution Start"
Write-Host "================================"
Write-Host "Timestamp: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss.fff')"
Write-Host "Environment: PYTHONHASHSEED=$($env:PYTHONHASHSEED), SONIA_TEST_MODE=$($env:SONIA_TEST_MODE)"
Write-Host ""

# Step 1: Verify Miniconda Installation
Write-Host "[STEP 1] Verifying Python Installation..."
$pythonPath = "C:\Miniconda3\python.exe"

if (Test-Path $pythonPath) {
    Write-Host "✓ Miniconda3 installation found at $pythonPath"
    & $pythonPath --version
    Write-Host ""
} else {
    Write-Host "✗ Miniconda3 not found at $pythonPath"
    Write-Host "Installing Miniconda3 now..."
    $installerPath = "S:\tools\sysprog\Miniconda3-py311_25.11.1-1-Windows-x86_64.exe"
    if (Test-Path $installerPath) {
        Write-Host "  Executing: $installerPath /InstallationType=JustMe /RegisterPython=1 /S /D=C:\Miniconda3"
        & $installerPath /InstallationType=JustMe /RegisterPython=1 /S /D=C:\Miniconda3
        Start-Sleep -Seconds 5
        
        # Refresh PATH
        $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
        
        if (Test-Path $pythonPath) {
            Write-Host "✓ Miniconda3 installation succeeded"
            & $pythonPath --version
        } else {
            Write-Host "✗ Miniconda3 installation failed - python.exe not found"
            exit 2
        }
    } else {
        Write-Host "✗ Miniconda3 installer not found at $installerPath"
        exit 2
    }
}

Write-Host ""
Write-Host "[STEP 2] Executing Prerequisites (venv setup, dependencies)..."

# Step 2: Run Prerequisites
$preReqScript = "S:\scripts\testing\phase3-prereq.ps1"
if (Test-Path $preReqScript) {
    Write-Host "  Executing: $preReqScript"
    & $preReqScript
    if ($LASTEXITCODE -ne 0) {
        Write-Host "✗ Prerequisites failed with exit code $LASTEXITCODE"
        exit 2
    }
    Write-Host "✓ Prerequisites completed successfully"
} else {
    Write-Host "✗ Prerequisites script not found at $preReqScript"
    exit 2
}

Write-Host ""
Write-Host "[STEP 3] Executing Gate 1: Cycle & Health Check Validation..."
Write-Host "  Parameters: CycleCount=$CycleCount, HealthCheckDuration=$HealthCheckDurationMinutes min, StartupTimeout=$StartupTimeoutSeconds sec"

# Step 3: Run Gate 1
$gate1Script = "S:\scripts\testing\phase3-go-no-go.ps1"
if (Test-Path $gate1Script) {
    Write-Host "  Executing: $gate1Script -CycleCount $CycleCount -HealthCheckDurationMinutes $HealthCheckDurationMinutes -StartupTimeoutSeconds $StartupTimeoutSeconds"
    & $gate1Script -CycleCount $CycleCount -HealthCheckDurationMinutes $HealthCheckDurationMinutes -StartupTimeoutSeconds $StartupTimeoutSeconds
    $gate1ExitCode = $LASTEXITCODE
    Write-Host ""
    Write-Host "Gate 1 Exit Code: $gate1ExitCode"
    if ($gate1ExitCode -eq 0) {
        Write-Host "✓ GATE 1 PASSED"
    } else {
        Write-Host "✗ GATE 1 FAILED"
    }
    exit $gate1ExitCode
} else {
    Write-Host "✗ Gate 1 script not found at $gate1Script"
    exit 2
}
