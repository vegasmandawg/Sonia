<#
.SYNOPSIS
Phase 3 Go/No-Go Gate - Strict reliability validation with hard startup verification

.DESCRIPTION
Executes the Phase 3 Go/No-Go criteria with HARD BLOCKING on startup failure:
  1. 10 consecutive start/stop cycles (must verify PID files + process + healthz)
  2. Health check every 5s for 30 minutes (2,160 total checks)
  3. Integration suite run twice (deterministic results required)
  4. Release artifact capture

CRITICAL: Cannot pass without real service startup verification.
Blocks on: missing PID files, dead processes, failed healthz checks, zombie processes.

.EXAMPLE
$env:PYTHONHASHSEED="0"
$env:SONIA_TEST_MODE="deterministic"
.\phase3-go-no-go.ps1 -CycleCount 10 -HealthCheckDurationMinutes 30 -StartupTimeoutSeconds 90
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

# Service specification with PID file and error log locations
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

function Log {
    param([string]$Message, [string]$Level = "INFO")
    $LogMsg = "$(Get-Date -Format 'HH:mm:ss') [$Level] $Message"
    Write-Host $LogMsg
    Add-Content -Path $ReportFile -Value $LogMsg
}

function Invoke-StackStart {
    param([string]$Root = "S:\")
    $candidates = @(
        "$Root\scripts\ops\start-sonia-stack.ps1",
        "$Root\start-sonia-stack.ps1"
    ) | Where-Object { Test-Path $_ }

    if ($candidates.Count -eq 0) {
        throw "ERROR: No start-sonia-stack.ps1 found in $Root\scripts\ops or $Root"
    }

    & $candidates[0] -SkipHealthCheck | Out-Null
}

function Invoke-StackStop {
    param([string]$Root = "S:\")
    $candidates = @(
        "$Root\scripts\ops\stop-sonia-stack.ps1",
        "$Root\stop-sonia-stack.ps1"
    ) | Where-Object { Test-Path $_ }

    if ($candidates.Count -eq 0) {
        throw "ERROR: No stop-sonia-stack.ps1 found in $Root\scripts\ops or $Root"
    }

    & $candidates[0] | Out-Null
}

function Test-ServiceUp {
    param([hashtable]$svc)
    
    # Check PID file exists
    if (-not (Test-Path $svc.Pid)) {
        Log "Service $($svc.Name): PID file missing at $($svc.Pid)" "DEBUG"
        return $false
    }

    # Extract PID from file
    try {
        $procId = [int](Get-Content $svc.Pid -ErrorAction Stop | Select-Object -First 1)
    } catch {
        Log "Service $($svc.Name): Failed to read PID from $($svc.Pid)" "DEBUG"
        return $false
    }

    # Verify process exists
    $proc = Get-Process -Id $procId -ErrorAction SilentlyContinue
    if (-not $proc) {
        Log "Service $($svc.Name): Process $procId not running (PID file exists but process dead)" "DEBUG"
        return $false
    }

    # Verify healthz endpoint responds
    try {
        $resp = Invoke-WebRequest -Uri "http://127.0.0.1:$($svc.Port)/healthz" -TimeoutSec 2 -UseBasicParsing -ErrorAction Stop
        if ($resp.StatusCode -eq 200) {
            return $true
        }
    } catch {
        Log "Service $($svc.Name): healthz check failed on port $($svc.Port)" "DEBUG"
        return $false
    }

    return $false
}

function Wait-StackHealthy {
    param([int]$timeoutSec)
    
    $deadline = (Get-Date).AddSeconds($timeoutSec)

    do {
        $allUp = $true
        foreach ($svc in $ServiceSpec) {
            if (-not (Test-ServiceUp $svc)) {
                $allUp = $false
                break
            }
        }
        if ($allUp) {
            return $true
        }
        Start-Sleep -Seconds 1
    } while ((Get-Date) -lt $deadline)

    return $false
}

function Write-StartupDiagnostics {
    Write-Host "`n=== STARTUP DIAGNOSTICS ===" -ForegroundColor Red
    foreach ($svc in $ServiceSpec) {
        $pidExists = Test-Path $svc.Pid
        $procAlive = $false
        $procId = $null
        
        if ($pidExists) {
            try {
                $procId = [int](Get-Content $svc.Pid -ErrorAction Stop | Select-Object -First 1)
                $procAlive = [bool](Get-Process -Id $procId -ErrorAction SilentlyContinue)
            } catch {
                $procId = "ERROR"
            }
        }

        Write-Host "$($svc.Name): pidFile=$pidExists pid=$procId alive=$procAlive" -ForegroundColor Yellow

        try {
            $resp = Invoke-WebRequest -Uri "http://127.0.0.1:$($svc.Port)/healthz" -TimeoutSec 2 -UseBasicParsing -ErrorAction Stop
            Write-Host "  healthz: OK" -ForegroundColor Green
        } catch {
            Write-Host "  healthz: FAIL - $($_.Exception.Message)" -ForegroundColor Red
        }

        if (Test-Path $svc.ErrLog) {
            Write-Host "  error log tail:" -ForegroundColor Yellow
            Get-Content $svc.ErrLog -Tail 10 -ErrorAction SilentlyContinue | ForEach-Object { Write-Host "    $_" -ForegroundColor Red }
        }
    }
    Write-Host ""
}

Log "=== PHASE 3 GO/NO-GO GATE START ===" "HEADER"
Log "Timestamp: $Timestamp" "INFO"
Log "StartupTimeoutSeconds: $StartupTimeoutSeconds" "INFO"
Log "CycleCount: $CycleCount" "INFO"
Log "" "INFO"

# ============================================================================
# GATE 1: 10 Consecutive Start/Stop Cycles
# ============================================================================

Log "`n=== GATE 1: $CycleCount Consecutive Start/Stop Cycles ===" "HEADER"
Log "Each cycle MUST: start stack, verify all PIDs + processes + healthz, stop cleanly, zero zombies" "INFO"

$CyclesPassed = 0

for ($i = 1; $i -le $CycleCount; $i++) {
    Log "`nCycle $i/$CycleCount" "INFO"
    
    try {
        Log "  Starting stack..." "DEBUG"
        Invoke-StackStart -Root "S:\"
        
        Log "  Waiting for stack to become healthy (${StartupTimeoutSeconds}s timeout)..." "DEBUG"
        $healthy = Wait-StackHealthy -timeoutSec $StartupTimeoutSeconds
        
        if (-not $healthy) {
            Write-StartupDiagnostics
            Log "  FAIL - Stack did not become healthy within ${StartupTimeoutSeconds}s" "FAIL"
            throw "Gate 1 FAIL: Stack startup timeout on cycle $i"
        }
        
        Log "  Stack healthy - stopping..." "DEBUG"
        Invoke-StackStop -Root "S:\"
        Start-Sleep -Seconds 2
        
        # Enforce zero zombie PIDs
        foreach ($svc in $ServiceSpec) {
            if (Test-Path $svc.Pid) {
                try {
                    $procId = [int](Get-Content $svc.Pid -ErrorAction Stop | Select-Object -First 1)
                    $stillAlive = Get-Process -Id $procId -ErrorAction SilentlyContinue
                    if ($stillAlive) {
                        Log "  FAIL - Zombie process: $($svc.Name) pid=$procId still running after stop" "FAIL"
                        throw "Gate 1 FAIL: Zombie process for $($svc.Name) (pid $procId) on cycle $i"
                    }
                } catch {
                    if ($_ -match "Gate 1 FAIL") { throw $_ }
                    # PID file may not exist, that's OK
                }
            }
        }
        
        Log "  PASS - Cycle complete (PID cleanup verified)" "PASS"
        $CyclesPassed++
        
    } catch {
        Log "  FAIL - Cycle $i failed: $_" "FAIL"
        throw $_
    }
}

Log "`n=== GATE 1 RESULT ===" "SUMMARY"
Log "Cycles passed: $CyclesPassed/$CycleCount" "SUMMARY"

if ($CyclesPassed -ne $CycleCount) {
    Log "GATE 1 FAILED" "FAIL"
    exit 1
}

Log "GATE 1 PASSED" "PASS"

# ============================================================================
# GATE 2: Health Checks Every 5s for 30 Minutes (2,160 total checks)
# ============================================================================

Log "`n=== GATE 2: Health Checks ($HealthCheckDurationMinutes min) ===" "HEADER"
Log "Expected: 30 minutes / 5s interval = 360 intervals" "INFO"
Log "Expected: 360 intervals × 6 services = 2,160 total checks" "INFO"

Invoke-StackStart -Root "S:\"
if (-not (Wait-StackHealthy -timeoutSec $StartupTimeoutSeconds)) {
    Write-StartupDiagnostics
    throw "Gate 2 FAIL: Cannot start stack for health check phase"
}

$EndTime = (Get-Date).AddMinutes($HealthCheckDurationMinutes)
$IntervalCount = 0
$TotalChecks = 0
$FailCount = 0

while ((Get-Date) -lt $EndTime) {
    $IntervalCount++
    $IntervalHealthy = $true
    
    foreach ($svc in $ServiceSpec) {
        $TotalChecks++
        if (-not (Test-ServiceUp $svc)) {
            $IntervalHealthy = $false
            $FailCount++
        }
    }
    
    if ($IntervalHealthy) {
        Log "Interval $IntervalCount ($TotalChecks total checks): All healthy" "DEBUG"
    } else {
        Log "Interval $IntervalCount ($TotalChecks total checks): FAIL" "WARN"
    }
    
    Start-Sleep -Seconds 5
}

$ExpectedChecks = 360 * 6
Log "`n=== GATE 2 RESULT ===" "SUMMARY"
Log "Total checks: $TotalChecks (expected: $ExpectedChecks)" "SUMMARY"
Log "Intervals: $IntervalCount (expected: 360)" "SUMMARY"
Log "Failed checks: $FailCount (threshold: 0)" "SUMMARY"

if ($FailCount -gt 0 -or $TotalChecks -ne $ExpectedChecks) {
    Log "GATE 2 FAILED - Health checks incomplete or had failures" "FAIL"
    exit 1
}

Log "GATE 2 PASSED" "PASS"

# ============================================================================
# GATE 2B: Determinism Lock - Integration Suite (2x identical runs)
# ============================================================================

Log "`n=== GATE 2B: Integration Suite Determinism Lock ===" "HEADER"
Log "Requirement: Run 1 result MUST EQUAL Run 2 result exactly" "INFO"

Invoke-StackStop -Root "S:\"
Start-Sleep -Seconds 2
Invoke-StackStart -Root "S:\"
if (-not (Wait-StackHealthy -timeoutSec $StartupTimeoutSeconds)) {
    throw "Gate 2B FAIL: Cannot start stack for integration tests"
}

Log "Run 1: Executing integration tests..." "INFO"
$Output1 = & python -m pytest "S:\tests\integration\test_phase2_e2e.py" -v 2>&1
$Passed1 = ($Output1 | Select-String "passed" | Measure-Object).Count
$Failed1 = ($Output1 | Select-String "failed" | Measure-Object).Count

Log "Run 1 Result: $Passed1 passed, $Failed1 failed" "DEBUG"

Invoke-StackStop -Root "S:\"
Start-Sleep -Seconds 2
Invoke-StackStart -Root "S:\"
if (-not (Wait-StackHealthy -timeoutSec $StartupTimeoutSeconds)) {
    throw "Gate 2B FAIL: Cannot restart stack for second integration test run"
}

Log "Run 2: Executing integration tests..." "INFO"
$Output2 = & python -m pytest "S:\tests\integration\test_phase2_e2e.py" -v 2>&1
$Passed2 = ($Output2 | Select-String "passed" | Measure-Object).Count
$Failed2 = ($Output2 | Select-String "failed" | Measure-Object).Count

Log "Run 2 Result: $Passed2 passed, $Failed2 failed" "DEBUG"

Log "`n=== GATE 2B RESULT ===" "SUMMARY"
Log "Run 1: $Passed1 passed, $Failed1 failed" "SUMMARY"
Log "Run 2: $Passed2 passed, $Failed2 failed" "SUMMARY"

if ($Passed1 -eq $Passed2 -and $Failed1 -eq $Failed2) {
    Log "DETERMINISTIC: Run 1 === Run 2 (Both: $Passed1 passed, $Failed1 failed)" "PASS"
    Log "GATE 2B PASSED" "PASS"
} else {
    Log "NON-DETERMINISTIC DETECTED - Results differ between runs" "FAIL"
    Log "GATE 2B FAILED" "FAIL"
    exit 1
}

# ============================================================================
# GATE 3: Release Artifact Bundle
# ============================================================================

Log "`n=== GATE 3: Capture Release Artifact Bundle ===" "HEADER"

$ArtifactDir = Join-Path $OutputDir "bundle-$Timestamp"
New-Item -ItemType Directory -Path $ArtifactDir -Force | Out-Null

# Capture logs
Log "Capturing service logs..." "DEBUG"
New-Item -ItemType Directory -Path (Join-Path $ArtifactDir "logs") -Force | Out-Null
Get-ChildItem "S:\logs\services\*" -ErrorAction SilentlyContinue | ForEach-Object {
    Copy-Item -Path $_.FullName -Destination (Join-Path $ArtifactDir "logs") -Force -ErrorAction SilentlyContinue
}

# Capture config hash
Log "Capturing config hash..." "DEBUG"
if (Test-Path "S:\config\sonia-config.json") {
    $ConfigHash = (Get-FileHash -Path "S:\config\sonia-config.json" -Algorithm SHA256).Hash
} else {
    $ConfigHash = "NOT_FOUND"
}

@{
    Timestamp = Get-Date -Format "o"
    ConfigHash = $ConfigHash
} | ConvertTo-Json | Out-File -Path (Join-Path $ArtifactDir "config-hash.json") -Encoding UTF8

# Capture running PIDs
Log "Capturing running process IDs..." "DEBUG"
$Procs = Get-Process python -ErrorAction SilentlyContinue
@{
    Count = if ($Procs) { $Procs.Count } else { 0 }
    PIDs = if ($Procs) { @($Procs.Id) } else { @() }
} | ConvertTo-Json | Out-File -Path (Join-Path $ArtifactDir "pids.json") -Encoding UTF8

# Capture requirements locks
Log "Capturing dependency locks..." "DEBUG"
New-Item -ItemType Directory -Path (Join-Path $ArtifactDir "locks") -Force | Out-Null
Get-ChildItem "S:\services\*/requirements.lock" -ErrorAction SilentlyContinue | ForEach-Object {
    Copy-Item -Path $_.FullName -Destination (Join-Path $ArtifactDir "locks") -Force -ErrorAction SilentlyContinue
}

Log "Artifact bundle saved to: $ArtifactDir" "PASS"
Log "GATE 3 PASSED" "PASS"

# ============================================================================
# Final Report and Summary
# ============================================================================

Log "`n=== PHASE 3 GO/NO-GO GATE - FINAL REPORT ===" "HEADER"
Log "ALL GATES PASSED" "PASS"
Log "Gate 1: $CyclesPassed/$CycleCount cycles" "PASS"
Log "Gate 2: $TotalChecks/$ExpectedChecks checks, $FailCount failures" "PASS"
Log "Gate 2B: Run 1 === Run 2 ($Passed1 passed, $Failed1 failed)" "PASS"
Log "Gate 3: Release artifacts captured" "PASS"

# Save JSON summary
$SummaryFile = Join-Path $OutputDir "go-no-go-summary-$Timestamp.json"
@{
    Status = "PASSED"
    Timestamp = Get-Date -Format "o"
    GateCounts = @{
        Gate1 = @{
            Cycles = $CyclesPassed
            Total = $CycleCount
            ZeroPIDs = $true
        }
        Gate2 = @{
            TotalChecks = $TotalChecks
            ExpectedChecks = $ExpectedChecks
            Intervals = $IntervalCount
            Failures = $FailCount
        }
        Gate2B = @{
            Run1 = @{ Passed = $Passed1; Failed = $Failed1 }
            Run2 = @{ Passed = $Passed2; Failed = $Failed2 }
            Deterministic = ($Passed1 -eq $Passed2 -and $Failed1 -eq $Failed2)
        }
        Gate3 = @{
            ArtifactDir = $ArtifactDir
        }
    }
} | ConvertTo-Json | Out-File -Path $SummaryFile -Encoding UTF8

Log "`nReport: $ReportFile" "INFO"
Log "Summary: $SummaryFile" "INFO"
Log "`nRELEASE CANDIDATE READY FOR VALIDATION" "PASS"

exit 0
