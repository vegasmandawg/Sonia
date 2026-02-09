# Wait for Python installation and then execute Gate 1

param(
    [int]$MaxWaitSeconds = 600,
    [int]$CheckIntervalSeconds = 10
)

Write-Host ""
Write-Host "=========================================="
Write-Host "Waiting for Python Installation"
Write-Host "=========================================="
Write-Host "Time: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss.fff')"
Write-Host "Max Wait: $MaxWaitSeconds seconds"
Write-Host ""

$pythonPath = "S:\tools\python\python.exe"
$startTime = Get-Date
$maxTime = $startTime.AddSeconds($MaxWaitSeconds)
$checkCount = 0

while ((Get-Date) -lt $maxTime) {
    $checkCount++
    $elapsed = (Get-Date) - $startTime
    
    if (Test-Path $pythonPath) {
        Write-Host "✓ Python executable found at: $pythonPath"
        Write-Host "  Check #$checkCount, Elapsed: $([int]$elapsed.TotalSeconds)s"
        Write-Host ""
        Write-Host "Testing Python installation..."
        
        $pythonVersion = & $pythonPath --version 2>&1
        $pythonExitCode = $LASTEXITCODE
        
        if ($pythonExitCode -eq 0) {
            Write-Host "✓ Python is working: $pythonVersion"
            Write-Host ""
            Write-Host "=========================================="
            Write-Host "PROCEEDING TO GATE 1"
            Write-Host "=========================================="
            Write-Host "Environment Setup:"
            Write-Host "  PYTHONHASHSEED=0"
            Write-Host "  SONIA_TEST_MODE=deterministic"
            Write-Host "  Python: $pythonPath"
            Write-Host ""
            
            # Set deterministic environment
            $env:PYTHONHASHSEED = "0"
            $env:SONIA_TEST_MODE = "deterministic"
            
            # Execute Gate 1
            $gate1Script = "S:\scripts\testing\phase3-go-no-go.ps1"
            if (Test-Path $gate1Script) {
                Write-Host "Executing Gate 1..."
                & $gate1Script -CycleCount 10 -HealthCheckDurationMinutes 30 -StartupTimeoutSeconds 90
                exit $LASTEXITCODE
            } else {
                Write-Host "✗ Gate 1 script not found: $gate1Script"
                exit 2
            }
        } else {
            Write-Host "✗ Python test failed with exit code $pythonExitCode"
            Write-Host "  Output: $pythonVersion"
            exit 1
        }
    }
    
    # Not found yet
    $remainingSeconds = [int]($maxTime - (Get-Date)).TotalSeconds
    Write-Host "[$checkCount] Python not yet found. Elapsed: $([int]$elapsed.TotalSeconds)s, Remaining: ${remainingSeconds}s"
    
    if ($remainingSeconds -gt 0) {
        Start-Sleep -Seconds $CheckIntervalSeconds
    } else {
        break
    }
}

Write-Host ""
Write-Host "✗ Timeout: Python installation did not complete within $MaxWaitSeconds seconds"
Write-Host ""
Write-Host "Troubleshooting:"
Write-Host "1. Check if installer process is still running"
Write-Host "2. Check debug log"
Write-Host "3. Check python directory size/contents"
Write-Host ""

exit 1
