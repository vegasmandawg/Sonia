# Wait for Python and execute Gate 1

param(
    [int]$MaxWaitSeconds = 600,
    [int]$CheckIntervalSeconds = 10
)

Write-Host "Waiting for Python installation..."

$pythonPath = "S:\tools\python\python.exe"
$startTime = Get-Date
$maxTime = $startTime.AddSeconds($MaxWaitSeconds)
$checkCount = 0

while ((Get-Date) -lt $maxTime) {
    $checkCount++
    $elapsed = (Get-Date) - $startTime
    
    if (Test-Path $pythonPath) {
        Write-Host "Python found!"
        $pythonVersion = & $pythonPath --version 2>&1
        
        if ($LASTEXITCODE -eq 0) {
            Write-Host "Python working: $pythonVersion"
            
            $env:PYTHONHASHSEED = "0"
            $env:SONIA_TEST_MODE = "deterministic"
            
            Write-Host "Executing Gate 1..."
            & "S:\scripts\testing\phase3-go-no-go.ps1" -CycleCount 10 -HealthCheckDurationMinutes 30 -StartupTimeoutSeconds 90
            exit $LASTEXITCODE
        }
    }
    
    $remainingSeconds = [int]($maxTime - (Get-Date)).TotalSeconds
    if ($remainingSeconds -gt 0) {
        Write-Host "Check $checkCount - Elapsed: $([int]$elapsed.TotalSeconds)s, Remaining: $remainingSeconds s"
        Start-Sleep -Seconds $CheckIntervalSeconds
    } else {
        break
    }
}

Write-Host "Timeout - Python installation did not complete"
exit 1
