# Wait for Python installation to complete
$pythonPath = "S:\tools\python\python.exe"
$maxWaitSeconds = 600
$checkIntervalSeconds = 5

$startTime = Get-Date
$maxWaitTime = $startTime.AddSeconds($maxWaitSeconds)

Write-Host "Waiting for Python installation to complete..."
Write-Host "Checking for: $pythonPath"
Write-Host "Max wait: $maxWaitSeconds seconds"
Write-Host ""

$iteration = 0
while ((Get-Date) -lt $maxWaitTime) {
    $iteration++
    
    if (Test-Path $pythonPath) {
        Write-Host "✓ Python executable found!"
        Write-Host "Verifying installation..."
        & $pythonPath --version
        
        if ($LASTEXITCODE -eq 0) {
            Write-Host "✓ Python is working!"
            exit 0
        } else {
            Write-Host "✗ Python executable found but failed to run"
            exit 1
        }
    }
    
    $elapsed = (Get-Date) - $startTime
    Write-Host "[$($iteration)s] Still installing... (elapsed: $([int]$elapsed.TotalSeconds)s)"
    
    Start-Sleep -Seconds $checkIntervalSeconds
}

Write-Host "✗ Timeout: Python installation did not complete within $maxWaitSeconds seconds"
exit 1
