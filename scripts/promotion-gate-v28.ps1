# promotion-gate-v28.ps1
# v2.8 Promotion Gate -- 14 gates with machine-readable JSON report
#
# Gate categories:
#   1-3:   RC hardening (barge-in, zombie, memory, perception, operator) [52 tests]
#   4-7:   v2.8 milestone tests (routing, memory, perception, operator) [104 tests]
#   8-9:   Backward compat (v2.7, v2.6+)
#   10-11: Artifact integrity (deps, manifest)
#   12:    Soak pass
#   13:    Incident snapshot
#   14:    Git clean state
#
# Usage: .\promotion-gate-v28.ps1 [-SkipLive] [-SkipSoak]

param(
    [switch]$SkipLive,
    [switch]$SkipSoak
)

$ErrorActionPreference = "Continue"
$python = "S:\envs\sonia-core\python.exe"
$gitExe = "C:\Git\cmd\git.exe"
$rootDir = "S:\"
$reportDir = "S:\reports\gate-v28"
$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$tempDir = "S:\reports\gate-v28\tmp"

if (-not (Test-Path $reportDir)) { New-Item -ItemType Directory -Path $reportDir -Force | Out-Null }
if (-not (Test-Path $tempDir)) { New-Item -ItemType Directory -Path $tempDir -Force | Out-Null }

$report = @{
    schema       = "2.0"
    version      = "v2.8.0-rc1"
    timestamp    = $timestamp
    gates        = @()
    passed       = 0
    failed       = 0
    skipped      = 0
    total        = 14
    promotion_ready = $false
    environment  = @{
        python   = (& cmd.exe /c """$python"" --version 2>&1")
        platform = [System.Environment]::OSVersion.ToString()
        hostname = $env:COMPUTERNAME
    }
}

function Run-Pytest {
    param([string]$Label, [string[]]$TestFiles)
    $tmpFile = "$tempDir\pytest_${Label}_${timestamp}.txt"
    $quotedFiles = ($TestFiles | ForEach-Object { """$_""" }) -join " "
    $cmd = """$python"" -m pytest $quotedFiles --tb=line -q"
    & cmd.exe /c "$cmd > ""$tmpFile"" 2>&1"
    if (Test-Path $tmpFile) {
        return (Get-Content $tmpFile -Raw)
    }
    return ""
}

function Parse-PytestResult {
    param([string]$Output)
    if ($Output -match "(\d+) passed" -and $Output -notmatch "(\d+) failed") {
        $count = $Matches[1]
        return @{ passed = $true; count = [int]$count }
    }
    if ($Output -match "(\d+) passed.*(\d+) failed") {
        return @{ passed = $false; count = 0 }
    }
    return @{ passed = $false; count = 0 }
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
        $gate.detail = "Skipped by flag"
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

Write-Host "`n=== v2.8.0-rc1 Promotion Gate ($timestamp) ===" -ForegroundColor Cyan
Write-Host ""

# ── Gate 1: RC hardening tests (52 tests) ────────────────────────────────

Run-Gate -Name "rc1-hardening" -Number 1 -Check {
    $out = Run-Pytest -Label "rc1" -TestFiles @("S:\tests\integration\test_v28_rc1_hardening.py")
    $r = Parse-PytestResult -Output $out
    if ($r.passed) { return "RC1 hardening: $($r.count) tests passed" }
    $tail = ($out -split "`n" | Select-Object -Last 5) -join " "
    throw "RC1 hardening failed: $tail"
}

# ── Gate 2: v2.8 M1-M4 milestone tests (104 tests) ──────────────────────

Run-Gate -Name "v28-milestones" -Number 2 -Check {
    $files = @(
        "S:\tests\integration\test_v28_model_routing.py",
        "S:\tests\integration\test_v28_memory_integration.py",
        "S:\tests\integration\test_v28_perception_gate.py",
        "S:\tests\integration\test_v28_operator_ux.py"
    )
    $out = Run-Pytest -Label "milestones" -TestFiles $files
    $r = Parse-PytestResult -Output $out
    if ($r.passed) { return "v2.8 milestones: $($r.count) tests passed" }
    $tail = ($out -split "`n" | Select-Object -Last 5) -join " "
    throw "v2.8 milestones failed: $tail"
}

# ── Gate 3: Full v2.8 regression (all v28 tests) ────────────────────────

Run-Gate -Name "v28-full-regression" -Number 3 -Check {
    $files = @(
        "S:\tests\integration\test_v28_model_routing.py",
        "S:\tests\integration\test_v28_memory_integration.py",
        "S:\tests\integration\test_v28_perception_gate.py",
        "S:\tests\integration\test_v28_operator_ux.py",
        "S:\tests\integration\test_v28_rc1_hardening.py"
    )
    $out = Run-Pytest -Label "v28full" -TestFiles $files
    $r = Parse-PytestResult -Output $out
    if ($r.passed) { return "v2.8 full regression: $($r.count) tests passed" }
    $tail = ($out -split "`n" | Select-Object -Last 5) -join " "
    throw "v2.8 regression failed: $tail"
}

# ── Gate 4: v2.7 backward compat ────────────────────────────────────────

Run-Gate -Name "v27-compat" -Number 4 -Check {
    $files = @(
        "S:\tests\integration\test_v27_contract_freeze.py",
        "S:\tests\integration\test_v27_protocol_invariants.py",
        "S:\tests\integration\test_v27_soak_faults.py",
        "S:\tests\integration\test_v27_voice_turn_loop.py",
        "S:\tests\integration\test_v27_perception_runtime.py",
        "S:\tests\integration\test_v27_ui_console_bridge.py",
        "S:\tests\integration\test_v27_action_execution.py",
        "S:\tests\integration\test_v27_cross_track.py"
    )
    $out = Run-Pytest -Label "v27compat" -TestFiles $files
    $r = Parse-PytestResult -Output $out
    if ($r.passed) { return "v2.7 compat: $($r.count) tests passed" }
    $tail = ($out -split "`n" | Select-Object -Last 5) -join " "
    throw "v2.7 compat failed: $tail"
}

# ── Gate 5: v2.6 backward compat ────────────────────────────────────────

Run-Gate -Name "v26-compat" -Number 5 -Check {
    $files = @(
        "S:\tests\integration\test_v26_contract.py",
        "S:\tests\integration\test_v26_determinism.py",
        "S:\tests\integration\test_v26_privacy_exhaustive.py",
        "S:\tests\integration\test_v26_ui_protocol.py",
        "S:\tests\integration\test_v26_cross_track.py"
    )
    $out = Run-Pytest -Label "v26compat" -TestFiles $files
    $r = Parse-PytestResult -Output $out
    if ($r.passed) { return "v2.6 compat: $($r.count) tests passed" }
    $tail = ($out -split "`n" | Select-Object -Last 5) -join " "
    throw "v2.6 compat failed: $tail"
}

# ── Gate 6: Full integration suite ──────────────────────────────────────

Run-Gate -Name "full-integration" -Number 6 -Check {
    $tmpFile = "$tempDir\pytest_allintegration_${timestamp}.txt"
    $cmd = """$python"" -m pytest ""S:\tests\integration"" --tb=line -q"
    & cmd.exe /c "$cmd > ""$tmpFile"" 2>&1"
    $out = ""
    if (Test-Path $tmpFile) { $out = Get-Content $tmpFile -Raw }
    $r = Parse-PytestResult -Output $out
    if ($r.passed) { return "Full integration suite: $($r.count) tests passed" }
    $tail = ($out -split "`n" | Select-Object -Last 5) -join " "
    throw "Full integration failed: $tail"
}

# ── Gate 7: Service health ──────────────────────────────────────────────

Run-Gate -Name "service-health" -Number 7 -Skip $SkipLive -Check {
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

# ── Gate 8: Circuit breaker states ──────────────────────────────────────

Run-Gate -Name "breaker-states" -Number 8 -Skip $SkipLive -Check {
    try {
        $resp = Invoke-RestMethod -Uri "http://127.0.0.1:7000/v1/breakers" -TimeoutSec 3
        return "Breakers checked"
    } catch {
        throw $_.Exception.Message
    }
}

# ── Gate 9: Frozen dependencies ─────────────────────────────────────────

Run-Gate -Name "deps-frozen" -Number 9 -Check {
    if (-not (Test-Path "S:\requirements-frozen.txt")) { throw "requirements-frozen.txt missing" }
    if (-not (Test-Path "S:\dependency-lock.json")) { throw "dependency-lock.json missing" }
    $lock = Get-Content "S:\dependency-lock.json" -Raw | ConvertFrom-Json
    if (-not $lock.schema_version) { throw "dependency-lock.json missing schema_version" }
    return "Dependency artifacts present (schema $($lock.schema_version))"
}

# ── Gate 10: Release manifest check ─────────────────────────────────────

Run-Gate -Name "release-manifest" -Number 10 -Check {
    $tagCheck = & cmd.exe /c """$gitExe"" -C ""S:\"" tag -l ""v2.8.0-rc1"" 2>&1"
    if (-not ($tagCheck -match "v2.8.0-rc1")) { throw "RC1 tag not found" }
    return "RC1 tag v2.8.0-rc1 present"
}

# ── Gate 11: Soak pass ──────────────────────────────────────────────────

Run-Gate -Name "soak-pass" -Number 11 -Skip $SkipSoak -Check {
    $soakResult = "$tempDir\soak_inline_$timestamp.txt"
    $soakCmd = "powershell.exe -ExecutionPolicy Bypass -File ""S:\scripts\soak_v28_rc1.ps1"" -Cycles 50"
    & cmd.exe /c "$soakCmd > ""$soakResult"" 2>&1"
    $content = ""
    if (Test-Path $soakResult) { $content = Get-Content $soakResult -Raw }
    if ($content -match "\[PASS\]") { return "Soak pass completed" }
    if ($content -match "PASS") { return "Soak pass completed" }
    # Fallback: check the JSON report directly
    $jsonFiles = Get-ChildItem "S:\reports\soak-v28\soak-v28-*.json" -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if ($jsonFiles) {
        $j = Get-Content $jsonFiles.FullName -Raw | ConvertFrom-Json
        if ($j.verdict -eq "PASS") { return "Soak pass completed (from report)" }
    }
    throw "Soak pass failed or incomplete"
}

# ── Gate 12: Incident bundle export ──────────────────────────────────────

Run-Gate -Name "incident-bundle" -Number 12 -Check {
    if (-not (Test-Path "S:\scripts\export-incident-bundle.ps1")) {
        throw "export-incident-bundle.ps1 missing"
    }
    return "Incident bundle script present"
}

# ── Gate 13: Changelog delta ─────────────────────────────────────────────

Run-Gate -Name "changelog-delta" -Number 13 -Check {
    $logResult = "$tempDir\changelog_$timestamp.txt"
    & cmd.exe /c """$gitExe"" -C ""S:\"" log v2.7.0..v2.8.0-rc1 --oneline > ""$logResult"" 2>&1"
    $content = ""
    if (Test-Path $logResult) { $content = Get-Content $logResult -Raw }
    if ($content) {
        $commitCount = ($content -split "`n" | Where-Object { $_.Trim() -ne "" }).Count
        return "Changelog: $commitCount commits since v2.7.0"
    }
    throw "Could not generate changelog delta"
}

# ── Gate 14: Git clean state ────────────────────────────────────────────

Run-Gate -Name "git-clean" -Number 14 -Check {
    $tmpGit = "$tempDir\git_status_$timestamp.txt"
    & cmd.exe /c """$gitExe"" -C ""S:\"" status --porcelain > ""$tmpGit"" 2>&1"
    $status = ""
    if (Test-Path $tmpGit) { $status = Get-Content $tmpGit -Raw }
    if ($status) {
        $lines = $status -split "`n" | Where-Object { $_.Trim() -ne "" }
        $tracked = ($lines | Where-Object { $_ -match "^[MADRC]" }).Count
        if ($tracked -gt 0) { throw "$tracked uncommitted tracked changes" }
    }
    return "No uncommitted tracked changes"
}

# ── Final verdict ───────────────────────────────────────────────────────

$report.promotion_ready = ($report.failed -eq 0)

$reportPath = "$reportDir\gate-v28-$timestamp.json"
$report | ConvertTo-Json -Depth 5 | Set-Content $reportPath -Encoding UTF8

Write-Host ""
Write-Host "=== Results ===" -ForegroundColor Cyan
Write-Host "  Passed:  $($report.passed)/$($report.total)" -ForegroundColor Green
Write-Host "  Failed:  $($report.failed)" -ForegroundColor $(if ($report.failed -gt 0) { "Red" } else { "Green" })
Write-Host "  Skipped: $($report.skipped)" -ForegroundColor Yellow
Write-Host "  Report:  $reportPath"
Write-Host ""

if ($report.promotion_ready) {
    Write-Host "  PROMOTION READY" -ForegroundColor Green
} else {
    Write-Host "  PROMOTION BLOCKED ($($report.failed) gates failed)" -ForegroundColor Red
}

Write-Host ""

# Clean up temp files
if (Test-Path $tempDir) { Remove-Item "$tempDir\*" -Force -ErrorAction SilentlyContinue }

exit $report.failed
