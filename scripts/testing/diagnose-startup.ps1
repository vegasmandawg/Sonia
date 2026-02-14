# Comprehensive startup failure diagnostic

Write-Host "===================================================="
Write-Host "PHASE 3 GATE 1 STARTUP DIAGNOSTIC"
Write-Host "===================================================="
Write-Host ""

# Set error handling to capture everything
$ErrorActionPreference = "Continue"

Write-Host "STEP 1: Check required directories"
Write-Host "---"
$dirs = @(
    "S:\state\pids",
    "S:\logs\services",
    "S:\config",
    "S:\artifacts\phase3"
)

foreach ($dir in $dirs) {
    if (Test-Path $dir) {
        Write-Host "[OK] $dir EXISTS"
    } else {
        Write-Host "[FAIL] $dir MISSING - Creating..."
        New-Item -ItemType Directory -Path $dir -Force | Out-Null
        Write-Host "  Created"
    }
}

Write-Host ""
Write-Host "STEP 2: Check start-sonia-stack.ps1 exists"
Write-Host "---"
$startScript = "S:\start-sonia-stack.ps1"
if (Test-Path $startScript) {
    Write-Host "[OK] Found: $startScript"
    $lines = (Get-Content $startScript | Measure-Object -Line).Lines
    Write-Host "  Lines: $lines"
} else {
    Write-Host "[FAIL] NOT FOUND: $startScript"
    exit 1
}

Write-Host ""
Write-Host "STEP 3: Test start script execution with error capture"
Write-Host "---"
Write-Host "Executing: & '$startScript' -SkipHealthCheck"
Write-Host ""

try {
    $output = & $startScript -SkipHealthCheck 2>&1
    $exitCode = $LASTEXITCODE
    
    Write-Host "Exit Code: $exitCode"
    Write-Host ""
    
    Write-Host "Output:"
    Write-Host "---"
    if ($output) {
        $output | ForEach-Object { Write-Host $_ }
    } else {
        Write-Host "(no output captured)"
    }
    
} catch {
    Write-Host "EXCEPTION CAUGHT:"
    Write-Host $_.Exception.Message
    Write-Host ""
    Write-Host "Stack Trace:"
    Write-Host $_.ScriptStackTrace
}

Write-Host ""
Write-Host "STEP 4: Check if any services started"
Write-Host "---"
$pids = @(
    "S:\state\pids\api-gateway.pid",
    "S:\state\pids\model-router.pid",
    "S:\state\pids\memory-engine.pid",
    "S:\state\pids\pipecat.pid",
    "S:\state\pids\openclaw.pid",
    "S:\state\pids\eva-os.pid"
)

$anyStarted = $false
foreach ($pidFile in $pids) {
    if (Test-Path $pidFile) {
        $pidValue = Get-Content $pidFile | Select-Object -First 1
        $proc = Get-Process -Id $pidValue -ErrorAction SilentlyContinue
        if ($proc) {
            Write-Host "[OK] $(Split-Path $pidFile -Leaf): PID $pidValue is RUNNING"
            $anyStarted = $true
        } else {
            Write-Host "[FAIL] $(Split-Path $pidFile -Leaf): PID file exists ($pidValue) but process not running"
        }
    } else {
        Write-Host "[FAIL] $(Split-Path $pidFile -Leaf): No PID file"
    }
}

if (-not $anyStarted) {
    Write-Host ""
    Write-Host "[WARN] No services appear to be running"
}

Write-Host ""
Write-Host "STEP 5: Check service log files for errors"
Write-Host "---"
$logDir = "S:\logs\services"
if (Test-Path $logDir) {
    $logs = Get-ChildItem $logDir -Filter "*.log" -ErrorAction SilentlyContinue
    if ($logs) {
        foreach ($log in $logs) {
            Write-Host ""
            Write-Host "File: $($log.Name)"
            Write-Host "Size: $($log.Length) bytes"
            if ($log.Length -gt 0) {
                Write-Host "Last 20 lines:"
                Get-Content $log.FullName -Tail 20 | ForEach-Object { Write-Host "  $_" }
            } else {
                Write-Host "  (empty)"
            }
        }
    } else {
        Write-Host "No log files found in $logDir"
    }
} else {
    Write-Host "Log directory does not exist: $logDir"
}

Write-Host ""
Write-Host "STEP 6: Check for Python issues"
Write-Host "---"
$python = "S:\tools\python\python.exe"
if (Test-Path $python) {
    Write-Host "[OK] Python found: $python"
    & $python --version
} else {
    Write-Host "[FAIL] Python NOT found"
}

Write-Host ""
Write-Host "STEP 7: Test healthz endpoints"
Write-Host "---"
$ports = @(7000, 7010, 7020, 7030, 7040, 7050)
foreach ($port in $ports) {
    try {
        $resp = Invoke-WebRequest -Uri "http://127.0.0.1:$port/healthz" -TimeoutSec 2 -UseBasicParsing -ErrorAction Stop
        Write-Host "[OK] Port ${port}: Responding (status $($resp.StatusCode))"
    } catch {
        Write-Host "[FAIL] Port ${port}: No response ($($_.Exception.GetBaseException().Message))"
    }
}

Write-Host ""
Write-Host "===================================================="
Write-Host "DIAGNOSTIC COMPLETE"
Write-Host "===================================================="
