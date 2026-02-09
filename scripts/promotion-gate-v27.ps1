# promotion-gate-v27.ps1
# v2.7 Promotion Gate -- 12 gates with machine-readable JSON report
# Includes streaming-specific hazards: protocol invariants, DLQ behavior,
# concurrency, latency budgets, soak with faults
#
# Usage: .\promotion-gate-v27.ps1 [-SkipLive]
# -SkipLive: skip gates requiring live services (health, breakers)

param(
    [switch]$SkipLive
)

$ErrorActionPreference = "Continue"
$python = "S:\envs\sonia-core\python.exe"
$gitExe = "C:\Git\cmd\git.exe"
$rootDir = "S:\"
$reportDir = "S:\reports\gate-v27"
$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$tempDir = "S:\reports\gate-v27\tmp"

if (-not (Test-Path $reportDir)) { New-Item -ItemType Directory -Path $reportDir -Force | Out-Null }
if (-not (Test-Path $tempDir)) { New-Item -ItemType Directory -Path $tempDir -Force | Out-Null }

$report = @{
    schema       = "2.0"
    version      = "v2.7.0"
    timestamp    = $timestamp
    gates        = @()
    passed       = 0
    failed       = 0
    skipped      = 0
    total        = 12
    promotion_ready = $false
}

function Run-Pytest {
    param([string]$Label, [string[]]$TestFiles)
    $tmpFile = "$tempDir\pytest_${Label}_${timestamp}.txt"
    # Build pytest command with proper quoting for cmd.exe
    $quotedFiles = ($TestFiles | ForEach-Object { """$_""" }) -join " "
    $cmd = """$python"" -m pytest $quotedFiles --tb=line -q"
    & cmd.exe /c "$cmd > ""$tmpFile"" 2>&1"
    if (Test-Path $tmpFile) {
        $content = Get-Content $tmpFile -Raw
        return $content
    }
    return ""
}

function Parse-PytestResult {
    param([string]$Output)
    # Look for "N passed" pattern in the output
    if ($Output -match "(\d+) passed" -and $Output -notmatch "(\d+) failed") {
        return $true
    }
    return $false
}

function Run-Gate {
    param([string]$Name, [int]$Number, [scriptblock]$Check, [bool]$Skip = $false)

    $t0 = Get-Date
    $gate = @{
        gate     = $Number
        name     = $Name
        status   = "pending"
        duration_ms = 0
        detail   = ""
    }

    if ($Skip) {
        $gate.status = "skipped"
        $gate.detail = "Skipped (requires live services)"
        $report.skipped++
        Write-Host "  Gate $Number [$Name]: SKIPPED" -ForegroundColor Yellow
    } else {
        try {
            $result = & $Check
            $gate.status = "passed"
            $gate.detail = if ($result) { "$result" } else { "OK" }
            $report.passed++
            Write-Host "  Gate $Number [$Name]: PASSED" -ForegroundColor Green
        } catch {
            $gate.status = "failed"
            $gate.detail = $_.Exception.Message
            $report.failed++
            Write-Host "  Gate $Number [$Name]: FAILED -- $($_.Exception.Message)" -ForegroundColor Red
        }
    }

    $elapsed = ((Get-Date) - $t0).TotalMilliseconds
    $gate.duration_ms = [math]::Round($elapsed, 1)
    $report.gates += $gate
}

Write-Host "`n=== v2.7.0 Promotion Gate ($timestamp) ===" -ForegroundColor Cyan
Write-Host ""

# Gate 1: Contract freeze tests (40 tests)
Run-Gate -Name "contract-freeze" -Number 1 -Check {
    $out = Run-Pytest -Label "contract" -TestFiles @("S:\tests\integration\test_v27_contract_freeze.py")
    if (Parse-PytestResult -Output $out) {
        return "Contract freeze tests passed"
    }
    $tail = ($out -split "`n" | Select-Object -Last 5) -join " "
    throw "Contract freeze failed: $tail"
}

# Gate 2: Protocol invariant tests (19 tests)
Run-Gate -Name "protocol-invariants" -Number 2 -Check {
    $out = Run-Pytest -Label "invariants" -TestFiles @("S:\tests\integration\test_v27_protocol_invariants.py")
    if (Parse-PytestResult -Output $out) {
        return "Protocol invariant tests passed"
    }
    $tail = ($out -split "`n" | Select-Object -Last 5) -join " "
    throw "Protocol invariants failed: $tail"
}

# Gate 3: Soak with faults (12 tests)
Run-Gate -Name "soak-faults" -Number 3 -Check {
    $out = Run-Pytest -Label "soak" -TestFiles @("S:\tests\integration\test_v27_soak_faults.py")
    if (Parse-PytestResult -Output $out) {
        return "Soak with fault injection passed"
    }
    $tail = ($out -split "`n" | Select-Object -Last 5) -join " "
    throw "Soak faults failed: $tail"
}

# Gate 4: Full v2.7 regression (all v27 test files)
Run-Gate -Name "regression" -Number 4 -Check {
    $files = @(
        "S:\tests\integration\test_v27_voice_turn_loop.py",
        "S:\tests\integration\test_v27_perception_runtime.py",
        "S:\tests\integration\test_v27_ui_console_bridge.py",
        "S:\tests\integration\test_v27_action_execution.py",
        "S:\tests\integration\test_v27_cross_track.py",
        "S:\tests\integration\test_v27_contract_freeze.py",
        "S:\tests\integration\test_v27_protocol_invariants.py",
        "S:\tests\integration\test_v27_soak_faults.py"
    )
    $out = Run-Pytest -Label "regression" -TestFiles $files
    if (Parse-PytestResult -Output $out) {
        return "Full v2.7 regression passed"
    }
    $tail = ($out -split "`n" | Select-Object -Last 5) -join " "
    throw "Regression failed: $tail"
}

# Gate 5: v2.6 backward compat
Run-Gate -Name "v26-compat" -Number 5 -Check {
    $files = @(
        "S:\tests\integration\test_v26_contract.py",
        "S:\tests\integration\test_v26_determinism.py",
        "S:\tests\integration\test_v26_privacy_exhaustive.py",
        "S:\tests\integration\test_v26_ui_protocol.py",
        "S:\tests\integration\test_v26_cross_track.py"
    )
    $out = Run-Pytest -Label "v26compat" -TestFiles $files
    if (Parse-PytestResult -Output $out) {
        return "v2.6 backward compat passed"
    }
    $tail = ($out -split "`n" | Select-Object -Last 5) -join " "
    throw "v2.6 compat failed: $tail"
}

# Gate 6: Service health checks
Run-Gate -Name "service-health" -Number 6 -Skip $SkipLive -Check {
    $ports = @(7000, 7010, 7020, 7030, 7040, 7050)
    $healthy = 0
    foreach ($p in $ports) {
        try {
            $resp = Invoke-RestMethod -Uri "http://127.0.0.1:${p}/healthz" -TimeoutSec 3
            if ($resp.status -eq "ok") { $healthy++ }
        } catch {}
    }
    if ($healthy -eq 6) { return "All 6 services healthy" }
    throw "Only $healthy/6 services healthy"
}

# Gate 7: Circuit breaker states
Run-Gate -Name "breaker-states" -Number 7 -Skip $SkipLive -Check {
    try {
        $resp = Invoke-RestMethod -Uri "http://127.0.0.1:7000/v1/breakers" -TimeoutSec 3
        $openBreakers = ($resp.breakers | Where-Object { $_.state -eq "open" }).Count
        if ($openBreakers -gt 0) { throw "$openBreakers breakers in OPEN state" }
        return "All breakers CLOSED"
    } catch {
        throw $_.Exception.Message
    }
}

# Gate 8: Frozen dependencies
Run-Gate -Name "deps-frozen" -Number 8 -Check {
    if (-not (Test-Path "S:\requirements-frozen.txt")) { throw "requirements-frozen.txt missing" }
    if (-not (Test-Path "S:\dependency-lock.json")) { throw "dependency-lock.json missing" }
    return "Dependency artifacts present"
}

# Gate 9: Release manifest
Run-Gate -Name "release-manifest" -Number 9 -Check {
    $lockContent = Get-Content "S:\dependency-lock.json" -Raw | ConvertFrom-Json
    if (-not $lockContent.schema_version) { throw "dependency-lock.json missing schema_version" }
    return "Release manifest valid (schema $($lockContent.schema_version))"
}

# Gate 10: DLQ depth check
Run-Gate -Name "dlq-depth" -Number 10 -Skip $SkipLive -Check {
    try {
        $resp = Invoke-RestMethod -Uri "http://127.0.0.1:7000/v1/dead-letters" -TimeoutSec 3
        $count = $resp.letters.Count
        if ($count -gt 50) { throw "DLQ has $count entries (threshold: 50)" }
        return "DLQ depth: $count (threshold: 50)"
    } catch {
        throw $_.Exception.Message
    }
}

# Gate 11: Incident bundle script exists
Run-Gate -Name "incident-bundle" -Number 11 -Check {
    if (-not (Test-Path "S:\scripts\export-incident-bundle.ps1")) {
        throw "export-incident-bundle.ps1 missing"
    }
    return "Incident bundle script present"
}

# Gate 12: Git clean state
Run-Gate -Name "git-clean" -Number 12 -Check {
    $tmpGit = "$tempDir\git_status_${timestamp}.txt"
    & cmd.exe /c """$gitExe"" -C ""S:\"" status --porcelain > ""$tmpGit"" 2>&1"
    $status = ""
    if (Test-Path $tmpGit) {
        $status = Get-Content $tmpGit -Raw
    }
    if ($status) {
        $lines = $status -split "`n" | Where-Object { $_.Trim() -ne "" }
        $tracked = ($lines | Where-Object { $_ -match "^[MADRC]" }).Count
        if ($tracked -gt 0) { throw "$tracked uncommitted tracked changes" }
    }
    return "No uncommitted tracked changes"
}

# Compute final status
$report.promotion_ready = ($report.failed -eq 0)

# Write JSON report
$reportPath = "$reportDir\gate-v27-$timestamp.json"
$report | ConvertTo-Json -Depth 5 | Set-Content $reportPath -Encoding UTF8

Write-Host ""
Write-Host "=== Results ===" -ForegroundColor Cyan
Write-Host "  Passed:  $($report.passed)" -ForegroundColor Green
Write-Host "  Failed:  $($report.failed)" -ForegroundColor $(if ($report.failed -gt 0) { "Red" } else { "Green" })
Write-Host "  Skipped: $($report.skipped)" -ForegroundColor Yellow
Write-Host "  Report:  $reportPath"
Write-Host ""

if ($report.promotion_ready) {
    Write-Host "  PROMOTION READY" -ForegroundColor Green
} else {
    Write-Host "  PROMOTION BLOCKED" -ForegroundColor Red
}

Write-Host ""

# Clean up temp files
if (Test-Path $tempDir) { Remove-Item "$tempDir\*" -Force -ErrorAction SilentlyContinue }
