<#
.SYNOPSIS
Phase 3 Gate 1 Execution - Hard Evidence Collection
Validates 10 consecutive start/stop cycles with strict service verification

.EXAMPLE
$env:PYTHONHASHSEED="0"
$env:SONIA_TEST_MODE="deterministic"
.\phase3-gate1-execute.ps1
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory=$false)]
    [int]$CycleCount = 10,
    
    [Parameter(Mandatory=$false)]
    [int]$HealthCheckDurationMinutes = 30,
    
    [Parameter(Mandatory=$false)]
    [int]$StartupTimeoutSeconds = 90
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

# Service specification
$ServiceSpec = @(
    @{ Name="api-gateway"; Port=7000; Pid="S:\state\pids\api-gateway.pid"; ErrLog="S:\logs\services\api-gateway.err.log" },
    @{ Name="model-router"; Port=7010; Pid="S:\state\pids\model-router.pid"; ErrLog="S:\logs\services\model-router.err.log" },
    @{ Name="memory-engine"; Port=7020; Pid="S:\state\pids\memory-engine.pid"; ErrLog="S:\logs\services\memory-engine.err.log" },
    @{ Name="pipecat"; Port=7030; Pid="S:\state\pids\pipecat.pid"; ErrLog="S:\logs\services\pipecat.err.log" },
    @{ Name="openclaw"; Port=7040; Pid="S:\state\pids\openclaw.pid"; ErrLog="S:\logs\services\openclaw.err.log" },
    @{ Name="eva-os"; Port=7050; Pid="S:\state\pids\eva-os.pid"; ErrLog="S:\logs\services\eva-os.err.log" }
)

$OutputDir = "S:\artifacts\phase3"
if (-not (Test-Path $OutputDir)) {
    New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null
}

$Timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$ReportFile = Join-Path $OutputDir "go-no-go-$Timestamp.log"
$SummaryFile = Join-Path $OutputDir "go-no-go-summary-$Timestamp.json"

function Log {
    param([string]$Message, [string]$Level = "INFO")
    $LogMsg = "$(Get-Date -Format 'HH:mm:ss') [$Level] $Message"
    Write-Host $LogMsg
    Add-Content -Path $ReportFile -Value $LogMsg
}

function Stop-AllServices {
    Log "Stopping all services..." "DEBUG"
    
    Get-Process | Where-Object { 
        $_.ProcessName -match "(python|node)" -and 
        $_.CommandLine -match "(api.gateway|model.router|memory.engine|pipecat|openclaw|eva.os)"
    } | ForEach-Object {
        Log "Terminating process: $($_.ProcessName) PID=$($_.Id)" "DEBUG"
        Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue
    }
    
    Start-Sleep -Seconds 1
}

function Start-AllServices {
    Log "Starting all services via start-sonia-stack-v2.ps1..." "DEBUG"
    
    # Try to invoke the v2 startup script
    $startScript = "S:\scripts\ops\start-sonia-stack-v2.ps1"
    if (-not (Test-Path $startScript)) {
        $startScript = "S:\scripts\ops\start-sonia-stack.ps1"
    }
    
    if (Test-Path $startScript) {
        try {
            # Use invocation operator to run startup script
            & $startScript -SkipHealthCheck
        } catch {
            Log "Start script failed, attempting direct service startup..." "WARN"
            # If startup script fails, launch services directly
            @(
                "S:\scripts\ops\run-api-gateway.ps1",
                "S:\scripts\ops\run-model-router.ps1",
                "S:\scripts\ops\run-memory-engine.ps1",
                "S:\scripts\ops\run-pipecat.ps1",
                "S:\scripts\ops\run-openclaw.ps1"
            ) | Where-Object { Test-Path $_ } | ForEach-Object {
                try {
                    . $_
                    Start-Sleep -Milliseconds 500
                } catch {
                    Log "Failed to start $_: $_" "ERROR"
                }
            }
        }
    }
    
    Start-Sleep -Seconds 2
}

function Test-ServiceUp {
    param([hashtable]$svc)
    
    # Check PID file exists
    if (-not (Test-Path $svc.Pid)) {
        return $false
    }

    # Extract PID from file
    try {
        $procId = [int](Get-Content $svc.Pid -ErrorAction Stop | Select-Object -First 1)
    } catch {
        return $false
    }

    # Verify process exists
    $proc = Get-Process -Id $procId -ErrorAction SilentlyContinue
    if (-not $proc) {
        return $false
    }

    # Check healthz endpoint
    try {
        $response = Invoke-WebRequest -Uri "http://127.0.0.1:$($svc.Port)/healthz" `
            -TimeoutSec 2 `
            -UseBasicParsing `
            -ErrorAction SilentlyContinue
        
        if ($response.StatusCode -eq 200) {
            return $true
        }
    } catch {
        return $false
    }
    
    return $false
}

function Wait-ServicesHealthy {
    param([int]$TimeoutSeconds = 90)
    
    $stopwatch = [System.Diagnostics.Stopwatch]::StartNew()
    
    while ($stopwatch.Elapsed.TotalSeconds -lt $TimeoutSeconds) {
        $healthyCount = 0
        
        foreach ($svc in $ServiceSpec) {
            if (Test-ServiceUp $svc) {
                $healthyCount++
            }
        }
        
        if ($healthyCount -eq $ServiceSpec.Count) {
            $stopwatch.Stop()
            Log "All services healthy in $([Math]::Round($stopwatch.Elapsed.TotalSeconds, 1))s" "INFO"
            return $true
        }
        
        Start-Sleep -Milliseconds 500
    }
    
    $stopwatch.Stop()
    Log "Timeout waiting for services: $([Math]::Round($stopwatch.Elapsed.TotalSeconds, 1))s / $TimeoutSeconds" "ERROR"
    return $false
}

# Main execution
Log "═══════════════════════════════════════════════════════════" "HEADER"
Log "Phase 3 Gate 1 Execution - Hard Evidence Collection" "HEADER"
Log "═══════════════════════════════════════════════════════════" "HEADER"
Log "StartupTimeoutSeconds: $StartupTimeoutSeconds" "INFO"
Log "CycleCount: $CycleCount" "INFO"
Log "" "INFO"

$cycleResults = @()
$totalZombieCount = 0
$healthCheckData = @{
    StartTime = Get-Date
    EndTime = $null
    TotalChecks = 0
    HealthyChecks = 0
    FailedChecks = 0
}

for ($cycle = 1; $cycle -le $CycleCount; $cycle++) {
    Log "Cycle $cycle/$CycleCount" "INFO"
    Log "  Starting stack..." "DEBUG"
    
    Stop-AllServices
    Start-Sleep -Seconds 1
    Start-AllServices
    
    # Wait for services to be healthy
    $healthy = Wait-ServicesHealthy $StartupTimeoutSeconds
    
    if (-not $healthy) {
        Log "  FAIL - Cycle $cycle failed: Services did not become healthy" "FAIL"
        $cycleResults += @{ Cycle=$cycle; Status="FAILED"; Reason="Timeout waiting for services" }
        continue
    }
    
    # Verify PID files and processes
    $allPidsValid = $true
    foreach ($svc in $ServiceSpec) {
        if (-not (Test-Path $svc.Pid)) {
            Log "  FAIL - Cycle $cycle: Missing PID file for $($svc.Name)" "FAIL"
            $allPidsValid = $false
            break
        }
        
        try {
            $procId = [int](Get-Content $svc.Pid -ErrorAction Stop | Select-Object -First 1)
            $proc = Get-Process -Id $procId -ErrorAction SilentlyContinue
            if (-not $proc) {
                Log "  FAIL - Cycle $cycle: Process dead for $($svc.Name)" "FAIL"
                $allPidsValid = $false
                break
            }
        } catch {
            Log "  FAIL - Cycle $cycle: Cannot read PID for $($svc.Name): $_" "FAIL"
            $allPidsValid = $false
            break
        }
    }
    
    if (-not $allPidsValid) {
        $cycleResults += @{ Cycle=$cycle; Status="FAILED"; Reason="PID validation failed" }
        continue
    }
    
    # Stop services
    Log "  Stopping stack..." "DEBUG"
    Stop-AllServices
    Start-Sleep -Seconds 1
    
    # Check for zombie processes
    $zombies = Get-Process | Where-Object { 
        $_.ProcessName -match "(python|node)" -and 
        $_.Handles -eq 0 -and
        $_.ProcessName -notmatch "(conhost|powershell)"
    }
    
    $zombieCount = $zombies.Count
    $totalZombieCount += $zombieCount
    
    if ($zombieCount -eq 0) {
        Log "  PASS - Cycle $cycle: All services stopped cleanly (zero zombies)" "PASS"
        $cycleResults += @{ Cycle=$cycle; Status="PASSED"; ZombieCount=0 }
    } else {
        Log "  WARNING - Cycle $cycle: $zombieCount zombie processes detected" "WARN"
        $cycleResults += @{ Cycle=$cycle; Status="PASSED_WITH_WARNINGS"; ZombieCount=$zombieCount }
    }
}

# Wait and conduct health check monitoring
Log "" "INFO"
Log "Running $HealthCheckDurationMinutes minute health check monitoring..." "INFO"
$healthCheckStartTime = Get-Date
$healthCheckEndTime = $healthCheckStartTime.AddMinutes($HealthCheckDurationMinutes)

# First, start services one more time
Stop-AllServices
Start-Sleep -Seconds 1
Start-AllServices
Wait-ServicesHealthy $StartupTimeoutSeconds | Out-Null

$healthCheckIntervalSeconds = 5
while ((Get-Date) -lt $healthCheckEndTime) {
    foreach ($svc in $ServiceSpec) {
        $healthCheckData.TotalChecks++
        
        if (Test-ServiceUp $svc) {
            $healthCheckData.HealthyChecks++
        } else {
            $healthCheckData.FailedChecks++
        }
    }
    
    Start-Sleep -Seconds $healthCheckIntervalSeconds
}

$healthCheckData.EndTime = Get-Date

# Build summary report
$passedCycles = ($cycleResults | Where-Object { $_.Status -match "PASSED" }).Count
$failedCycles = ($cycleResults | Where-Object { $_.Status -eq "FAILED" }).Count

$summary = @{
    Timestamp = $Timestamp
    Gate1 = @{
        Cycles = $CycleCount
        Passed = $passedCycles
        Failed = $failedCycles
        ZeroPIDs = ($totalZombieCount -eq 0)
        TotalZombies = $totalZombieCount
        CycleDetails = $cycleResults
    }
    Gate2 = @{
        TotalChecks = $healthCheckData.TotalChecks
        HealthyChecks = $healthCheckData.HealthyChecks
        FailedChecks = $healthCheckData.FailedChecks
        Duration_Minutes = $HealthCheckDurationMinutes
        ErrorRate_Percent = [Math]::Round(($healthCheckData.FailedChecks / $healthCheckData.TotalChecks) * 100, 2)
    }
    Gate2B = @{
        Deterministic = ($env:PYTHONHASHSEED -eq "0") -and ($env:SONIA_TEST_MODE -eq "deterministic")
        PythonHashSeed = $env:PYTHONHASHSEED
        TestMode = $env:SONIA_TEST_MODE
    }
    Validation = @{
        Gate1_Pass = ($failedCycles -eq 0) -and ($totalZombieCount -eq 0)
        Gate2_Pass = ($healthCheckData.FailedChecks -eq 0) -or ($healthCheckData.FailedChecks / $healthCheckData.TotalChecks -lt 0.005)
        Gate2B_Pass = ($env:PYTHONHASHSEED -eq "0")
    }
}

# Write JSON summary
$summary | ConvertTo-Json -Depth 10 | Out-File -FilePath $SummaryFile -Encoding UTF8

Log "" "INFO"
Log "═══════════════════════════════════════════════════════════" "HEADER"
Log "Gate 1 Results Summary" "HEADER"
Log "═══════════════════════════════════════════════════════════" "HEADER"
Log "Cycles Completed: $CycleCount" "INFO"
Log "Cycles Passed: $passedCycles" "INFO"
Log "Cycles Failed: $failedCycles" "INFO"
Log "Total Zombie Processes: $totalZombieCount" "INFO"
Log "Zero PIDs Validation: $(if ($totalZombieCount -eq 0) { 'PASS' } else { 'FAIL' })" "INFO"
Log "" "INFO"
Log "Gate 2 Health Check Results" "HEADER"
Log "Total Checks: $($healthCheckData.TotalChecks)" "INFO"
Log "Healthy Checks: $($healthCheckData.HealthyChecks)" "INFO"
Log "Failed Checks: $($healthCheckData.FailedChecks)" "INFO"
Log "Error Rate: $($summary.Gate2.ErrorRate_Percent)%" "INFO"
Log "" "INFO"
Log "Determinism Check" "HEADER"
Log "PYTHONHASHSEED: $($env:PYTHONHASHSEED)" "INFO"
Log "SONIA_TEST_MODE: $($env:SONIA_TEST_MODE)" "INFO"
Log "" "INFO"
Log "Summary written to: $SummaryFile" "INFO"
Log "═══════════════════════════════════════════════════════════" "HEADER"

# Clean exit code
if ($summary.Validation.Gate1_Pass -and $summary.Validation.Gate2_Pass) {
    Log "All validations PASSED - Gate 1 Ready" "PASS"
    exit 0
} else {
    Log "Validation FAILED - Check summary JSON" "FAIL"
    exit 1
}
