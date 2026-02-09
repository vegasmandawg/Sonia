# Phase 3 Gate 1: 10 Consecutive Start/Stop Cycles
# Safe version with ASCII-only characters for compatibility

[CmdletBinding()]
param(
    [Parameter(Mandatory=$false)]
    [string]$Root = "S:\",

    [Parameter(Mandatory=$false)]
    [int]$CycleCount = 10
)

$ErrorActionPreference = "Continue"
$OutputDir = "S:\artifacts\phase3"

# Create output directory
if (-not (Test-Path $OutputDir)) {
    New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null
}

$Timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$ReportFile = Join-Path $OutputDir "gate1-$Timestamp.log"

function Log {
    param([string]$Message, [string]$Level = "INFO")
    $LogMsg = "$(Get-Date -Format 'HH:mm:ss') [$Level] $Message"
    Write-Host $LogMsg
    Add-Content -Path $ReportFile -Value $LogMsg
}

Log "=== PHASE 3 GATE 1: START/STOP CYCLES ===" "HEADER"
Log "Cycles to complete: $CycleCount"
Log "Output: $ReportFile"
Log ""

$CyclesPassed = 0
$CyclesFailed = 0

for ($i = 1; $i -le $CycleCount; $i++) {
    Log "Cycle $i/$CycleCount: Starting..." "INFO"
    
    # Stop stack
    try {
        $StopOutput = & "$Root\phase3-stack-stop-safe.ps1" -Root $Root -ErrorAction SilentlyContinue 2>&1
        Log "Stopped services" "DEBUG"
    } catch {
        Log "Warning: Stop returned error (may be normal): $_" "WARN"
    }
    
    Start-Sleep -Seconds 3
    
    # Check for zombie processes
    $AllPython = Get-Process python -ErrorAction SilentlyContinue
    if ($AllPython) {
        Log "FAIL - Cycle $i: Found lingering Python processes" "FAIL"
        $CyclesFailed++
        continue
    }
    
    # Start stack
    try {
        $StartOutput = & "$Root\phase3-stack-start-safe.ps1" -Root $Root -SkipHealthCheck 2>&1
        Log "Started services" "DEBUG"
    } catch {
        Log "FAIL - Cycle $i: Start failed: $_" "FAIL"
        $CyclesFailed++
        continue
    }
    
    Start-Sleep -Seconds 8
    
    # Quick health check on all ports
    $AllHealthy = $true
    for ($port = 7000; $port -le 7050; $port += 10) {
        try {
            $Response = Invoke-WebRequest -Uri "http://127.0.0.1:$port/healthz" -TimeoutSec 2 -ErrorAction Stop
            if ($Response.StatusCode -ne 200) {
                Log "Port $port returned status $($Response.StatusCode)" "DEBUG"
                $AllHealthy = $false
                break
            }
        } catch {
            Log "Port $port failed: $($_.Exception.Message)" "DEBUG"
            $AllHealthy = $false
            break
        }
    }
    
    if ($AllHealthy) {
        Log "PASS - Cycle $i: All services healthy" "PASS"
        $CyclesPassed++
    } else {
        Log "FAIL - Cycle $i: Health check failed" "FAIL"
        $CyclesFailed++
    }
}

Log ""
Log "=== GATE 1 RESULTS ===" "HEADER"
Log "Cycles passed: $CyclesPassed/$CycleCount" "SUMMARY"
Log "Cycles failed: $CyclesFailed/$CycleCount" "SUMMARY"

if ($CyclesPassed -eq $CycleCount) {
    Log "GATE 1: PASSED" "PASS"
    
    # Generate JSON result
    $Result = @{
        Status = "PASS"
        Timestamp = Get-Date -Format "o"
        Gate = "Gate1"
        CyclesPassed = $CyclesPassed
        CyclesRequired = $CycleCount
        CyclesFailed = $CyclesFailed
    } | ConvertTo-Json
    
    $JsonFile = Join-Path $OutputDir "gate1-result-$Timestamp.json"
    $Result | Out-File -FilePath $JsonFile -Encoding UTF8
    Log "Result saved to: $JsonFile" "INFO"
    
    exit 0
} else {
    Log "GATE 1: FAILED" "FAIL"
    exit 1
}
