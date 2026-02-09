<#
.SYNOPSIS
Post-change qualification gate for Sonia.

.DESCRIPTION
Runs a deterministic qualification sequence after any code change:
  1. Static checks (Python syntax, PowerShell parse)
  2. Cold restart cycle
  3. Health smoke (6/6 services)
  4. Optional feature test
  5. Secret leak scan
  6. Dependency drift check
  7. Artifact packaging

Exit code 0 = all gates passed. Non-zero = hard fail.

.PARAMETER FeatureTest
Optional path to a feature-specific test script to run after health smoke.

.PARAMETER SkipRestart
Skip the restart cycle (use when services are already freshly started).

.EXAMPLE
.\scripts\qualify-change.ps1
.\scripts\qualify-change.ps1 -FeatureTest ".\tests\pipecat\test-voice-loop.ps1"
#>

[CmdletBinding()]
param(
    [string]$FeatureTest,
    [switch]$SkipRestart
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

. "S:\scripts\lib\sonia-stack.ps1"

$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$reportDir = "S:\reports\qualification_$stamp"
New-Item -ItemType Directory -Path $reportDir -Force | Out-Null

$gateResults = @()
$allPassed = $true

function Write-Gate {
    param([string]$Name, [bool]$Passed, [string]$Detail)
    $status = if ($Passed) { "PASS" } else { "FAIL" }
    $msg = "[$status] $Name"
    if ($Detail) { $msg += " -- $Detail" }
    Write-Host $msg -ForegroundColor $(if ($Passed) { "Green" } else { "Red" })
    $script:gateResults += "$status|$Name|$Detail"
    if (-not $Passed) { $script:allPassed = $false }
}

# ─────────────────────────────────────────────────────────────────────
# GATE 1: Static Checks
# ─────────────────────────────────────────────────────────────────────
Write-Host "`n=== GATE 1: Static Checks ===" -ForegroundColor Cyan

# Python syntax check via ast.parse (avoids .pyc file locks from running services)
$pyFail = @()
$savedEAP = $ErrorActionPreference
$ErrorActionPreference = 'SilentlyContinue'
Get-ChildItem -Path "S:\services" -Recurse -Filter "*.py" -File `
    | Where-Object { $_.FullName -notmatch '__pycache__' } `
    | ForEach-Object {
    $null = & "S:\envs\sonia-core\python.exe" -c "import ast,sys; ast.parse(open(sys.argv[1],'r',encoding='utf-8').read())" $_.FullName 2>&1
    if ($LASTEXITCODE -ne 0) { $pyFail += $_.FullName }
}
$ErrorActionPreference = $savedEAP
Write-Gate "Python syntax" ($pyFail.Count -eq 0) "$($pyFail.Count) errors"

# PowerShell parse check
$psFail = @()
foreach ($ps1 in @(
    "S:\start-sonia-stack.ps1",
    "S:\stop-sonia-stack.ps1",
    "S:\scripts\lib\sonia-stack.ps1",
    "S:\scripts\health-smoke.ps1"
)) {
    if (Test-Path $ps1) {
        try {
            $null = [System.Management.Automation.PSParser]::Tokenize((Get-Content $ps1 -Raw), [ref]$null)
        } catch {
            $psFail += $ps1
        }
    }
}
Write-Gate "PowerShell syntax" ($psFail.Count -eq 0) "$($psFail.Count) errors"

if (-not $allPassed) {
    Write-Host "`nStatic checks failed. Aborting." -ForegroundColor Red
    $gateResults | Out-File "$reportDir\gate-results.txt" -Encoding UTF8
    exit 1
}

# ─────────────────────────────────────────────────────────────────────
# GATE 2: Restart Cycle
# ─────────────────────────────────────────────────────────────────────
Write-Host "`n=== GATE 2: Restart Cycle ===" -ForegroundColor Cyan

if ($SkipRestart) {
    Write-Gate "Restart cycle" $true "SKIPPED (flag set)"
} else {
    # Stop
    $ports = @(7050, 7040, 7030, 7020, 7010, 7000)
    foreach ($p in $ports) {
        $conn = Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue
        if ($conn) {
            foreach ($c in $conn) {
                Stop-Process -Id $c.OwningProcess -Force -ErrorAction SilentlyContinue
            }
        }
    }
    Get-ChildItem "S:\state\pids" -Filter "*.pid" -ErrorAction SilentlyContinue | ForEach-Object {
        Remove-Item $_.FullName -Force -ErrorAction SilentlyContinue
    }
    Start-Sleep -Seconds 2

    # Start
    $startFail = @()
    $svcs = @(
        @{ Name="api-gateway";   Dir="S:\services\api-gateway";   Port=7000 },
        @{ Name="model-router";  Dir="S:\services\model-router";  Port=7010 },
        @{ Name="memory-engine"; Dir="S:\services\memory-engine"; Port=7020 },
        @{ Name="pipecat";       Dir="S:\services\pipecat";       Port=7030 },
        @{ Name="openclaw";      Dir="S:\services\openclaw";      Port=7040 },
        @{ Name="eva-os";        Dir="S:\services\eva-os";        Port=7050 }
    )
    foreach ($svc in $svcs) {
        try {
            Start-SoniaService -ServiceName $svc.Name -ServiceDir $svc.Dir -Port $svc.Port -BootWaitSeconds 12 | Out-Null
        } catch {
            $startFail += $svc.Name
        }
    }
    Write-Gate "Restart cycle" ($startFail.Count -eq 0) $(if ($startFail.Count -gt 0) { "Failed: $($startFail -join ', ')" } else { "6/6 started" })
}

if (-not $allPassed) {
    Write-Host "`nRestart cycle failed. Aborting." -ForegroundColor Red
    $gateResults | Out-File "$reportDir\gate-results.txt" -Encoding UTF8
    exit 2
}

# ─────────────────────────────────────────────────────────────────────
# GATE 3: Health Smoke
# ─────────────────────────────────────────────────────────────────────
Write-Host "`n=== GATE 3: Health Smoke ===" -ForegroundColor Cyan

$healthFail = @()
$healthChecks = @(
    @{ Name="api-gateway";   Port=7000 },
    @{ Name="model-router";  Port=7010 },
    @{ Name="memory-engine"; Port=7020 },
    @{ Name="pipecat";       Port=7030 },
    @{ Name="openclaw";      Port=7040 },
    @{ Name="eva-os";        Port=7050 }
)
foreach ($c in $healthChecks) {
    try {
        $r = Invoke-RestMethod -Uri "http://127.0.0.1:$($c.Port)/healthz" -TimeoutSec 5
        Write-Host "  [OK]  $($c.Name)" -ForegroundColor Green
    } catch {
        Write-Host "  [FAIL] $($c.Name)" -ForegroundColor Red
        $healthFail += $c.Name
    }
}
Write-Gate "Health smoke" ($healthFail.Count -eq 0) "$($healthChecks.Count - $healthFail.Count)/$($healthChecks.Count) healthy"

if (-not $allPassed) {
    Write-Host "`nHealth smoke failed. Aborting." -ForegroundColor Red
    $gateResults | Out-File "$reportDir\gate-results.txt" -Encoding UTF8
    exit 3
}

# ─────────────────────────────────────────────────────────────────────
# GATE 4: Feature Test (optional)
# ─────────────────────────────────────────────────────────────────────
Write-Host "`n=== GATE 4: Feature Test ===" -ForegroundColor Cyan

if ($FeatureTest) {
    if (Test-Path $FeatureTest) {
        try {
            & $FeatureTest
            Write-Gate "Feature test" ($LASTEXITCODE -eq 0 -or $null -eq $LASTEXITCODE) $FeatureTest
        } catch {
            Write-Gate "Feature test" $false "$FeatureTest -> $_"
        }
    } else {
        Write-Gate "Feature test" $false "Script not found: $FeatureTest"
    }
} else {
    Write-Gate "Feature test" $true "SKIPPED (none specified)"
}

# ─────────────────────────────────────────────────────────────────────
# GATE 5: Secret Leak Scan
# ─────────────────────────────────────────────────────────────────────
Write-Host "`n=== GATE 5: Secret Leak Scan ===" -ForegroundColor Cyan

$secretPatterns = @(
    'sk-[a-zA-Z0-9]{20,}',
    'AKIA[0-9A-Z]{16}',
    'ghp_[a-zA-Z0-9]{36}',
    'api[_-]?key\s*[:=]\s*["\x27][a-zA-Z0-9]{16,}',
    'password\s*[:=]\s*["\x27][^\s"'']{8,}'
)

$leaks = @()
$scanFiles = Get-ChildItem -Path "S:\services","S:\scripts","S:\config" -Recurse -Include "*.py","*.ps1","*.json","*.yaml","*.yml" -ErrorAction SilentlyContinue
foreach ($file in $scanFiles) {
    $content = Get-Content $file.FullName -Raw -ErrorAction SilentlyContinue
    if ($content) {
        foreach ($pattern in $secretPatterns) {
            if ($content -match $pattern) {
                $leaks += "$($file.FullName): matches $pattern"
            }
        }
    }
}
Write-Gate "Secret leak scan" ($leaks.Count -eq 0) "$($leaks.Count) potential leaks"
if ($leaks.Count -gt 0) {
    $leaks | Out-File "$reportDir\secret-leaks.txt" -Encoding UTF8
}

# ─────────────────────────────────────────────────────────────────────
# GATE 6: Dependency Drift
# ─────────────────────────────────────────────────────────────────────
Write-Host "`n=== GATE 6: Dependency Drift ===" -ForegroundColor Cyan

$baselineFreeze = "S:\baselines\Sonia-RC1-20260208\pip-freeze.txt"
if (Test-Path $baselineFreeze) {
    $baseline = @(Get-Content $baselineFreeze | Where-Object { $_ -match '\S' -and $_ -notmatch '^\s*#' })
    $current = @(& "S:\envs\sonia-core\python.exe" -m pip freeze 2>&1 | Where-Object { $_ -match '\S' })

    $baselineSet = @{}
    foreach ($line in $baseline) { $baselineSet[$line.Trim()] = $true }

    $newDeps = @()
    foreach ($line in $current) {
        if (-not $baselineSet.ContainsKey($line.Trim())) {
            $newDeps += $line.Trim()
        }
    }

    Write-Gate "Dependency drift" ($newDeps.Count -eq 0) "$($newDeps.Count) new/changed deps"
    if ($newDeps.Count -gt 0) {
        $newDeps | Out-File "$reportDir\dep-drift.txt" -Encoding UTF8
        foreach ($d in $newDeps) { Write-Host "  NEW: $d" -ForegroundColor Yellow }
    }
} else {
    Write-Gate "Dependency drift" $true "SKIPPED (no baseline freeze found)"
}

# ─────────────────────────────────────────────────────────────────────
# GATE 7: Error Log Scan
# ─────────────────────────────────────────────────────────────────────
Write-Host "`n=== GATE 7: Error Log Scan ===" -ForegroundColor Cyan

$logWarnings = 0
foreach ($svc in @("api-gateway","model-router","memory-engine","pipecat","openclaw","eva-os")) {
    $errLog = "S:\logs\services\$svc.err.log"
    if (Test-Path $errLog) {
        $content = @(Get-Content $errLog -ErrorAction SilentlyContinue)
        $warns = @($content | Where-Object { $_ -match "WARNING|ERROR|CRITICAL|Traceback" })
        $logWarnings += $warns.Count
    }
}
Write-Gate "Error log scan" ($logWarnings -eq 0) "$logWarnings warnings/errors in service logs"

# ─────────────────────────────────────────────────────────────────────
# Summary
# ─────────────────────────────────────────────────────────────────────
Write-Host "`n═══════════════════════════════════════════════════════════" -ForegroundColor Cyan

$gateResults | Out-File "$reportDir\gate-results.txt" -Encoding UTF8

if ($allPassed) {
    Write-Host "QUALIFICATION: PASSED" -ForegroundColor Green
    Write-Host "Report: $reportDir" -ForegroundColor Gray
    exit 0
} else {
    Write-Host "QUALIFICATION: FAILED" -ForegroundColor Red
    Write-Host "Report: $reportDir" -ForegroundColor Gray
    exit 1
}
