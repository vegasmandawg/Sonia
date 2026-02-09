# Validate Gate 1 real execution results
$ErrorActionPreference = "Stop"

Write-Host "Waiting for Gate 1 execution to complete..." -ForegroundColor Cyan
Write-Host "Checking S:\artifacts\phase3 for new summary JSON..." -ForegroundColor Yellow

# Find newest summary JSON (must be newer than invalidated one)
$invalidatedTime = (Get-Item "S:\artifacts\phase3\invalidated\go-no-go-summary-*.json" | Select-Object -First 1).LastWriteTime
$stopwatch = [System.Diagnostics.Stopwatch]::StartNew()

while ($stopwatch.Elapsed.TotalSeconds -lt 3600) {  # Wait up to 1 hour
    $summaries = @(Get-ChildItem "S:\artifacts\phase3\go-no-go-summary-*.json" -ErrorAction SilentlyContinue | 
        Where-Object { $_.DirectoryName -eq "S:\artifacts\phase3" -and $_.LastWriteTime -gt $invalidatedTime })
    
    if ($summaries.Count -gt 0) {
        $latest = $summaries | Sort-Object LastWriteTime -Descending | Select-Object -First 1
        Write-Host "Found new summary JSON: $($latest.Name)" -ForegroundColor Green
        
        try {
            $json = Get-Content $latest.FullName -Raw | ConvertFrom-Json
            
            # Validate hard assertions
            Write-Host "Validating assertions..." -ForegroundColor Yellow
            
            $assertions = @(
                @{ Name="Gate1.Cycles"; Value=$json.Gate1.Cycles; Expected=10 },
                @{ Name="Gate1.Passed"; Value=$json.Gate1.Passed; Expected=10 },
                @{ Name="Gate1.Failed"; Value=$json.Gate1.Failed; Expected=0 },
                @{ Name="Gate1.ZeroPIDs"; Value=$json.Gate1.ZeroPIDs; Expected=$true },
                @{ Name="Gate2.TotalChecks"; Value=$json.Gate2.TotalChecks; Expected=2160 },
                @{ Name="Gate2.FailedChecks"; Value=$json.Gate2.FailedChecks; Expected=0 }
            )
            
            $allPass = $true
            foreach ($assertion in $assertions) {
                if ($assertion.Value -eq $assertion.Expected) {
                    Write-Host "  [PASS] $($assertion.Name) = $($assertion.Value)" -ForegroundColor Green
                } else {
                    Write-Host "  [FAIL] $($assertion.Name) = $($assertion.Value) (expected $($assertion.Expected))" -ForegroundColor Red
                    $allPass = $false
                }
            }
            
            if ($allPass) {
                Write-Host "`nGate 1 VALID - All assertions passed" -ForegroundColor Green
                
                # Create hash bundle
                Write-Host "`nCreating hash bundle..." -ForegroundColor Yellow
                $timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
                $bundle = "S:\artifacts\phase3\gate-results\gate1-$timestamp"
                New-Item -ItemType Directory -Path $bundle -Force | Out-Null
                Copy-Item $latest.FullName $bundle -Force
                Get-ChildItem "S:\artifacts\phase3\go-no-go-*.log" | Copy-Item -Destination $bundle -Force -ErrorAction SilentlyContinue
                
                Get-ChildItem $bundle -File | Get-FileHash -Algorithm SHA256 | Sort-Object Path |
                    Export-Csv "$bundle\SHA256SUMS.csv" -NoTypeInformation
                
                Write-Host "Evidence bundle created at: $bundle" -ForegroundColor Green
                exit 0
            } else {
                Write-Host "`nGate 1 INVALID - Assertion failures detected" -ForegroundColor Red
                exit 1
            }
        }
        catch {
            Write-Host "ERROR parsing JSON: $_" -ForegroundColor Red
            exit 1
        }
    }
    
    Write-Host "Waiting... ($([Math]::Round($stopwatch.Elapsed.TotalSeconds))s / 3600s)" -ForegroundColor Gray
    Start-Sleep -Seconds 10
}

Write-Host "TIMEOUT: Gate 1 execution did not complete within 1 hour" -ForegroundColor Red
exit 2
