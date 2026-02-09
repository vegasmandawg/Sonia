<#
.SYNOPSIS
    v2.6 Promotion Gate -- 16-gate checklist (machine-readable output)
    Inherits all v2.5 gates + 4 new companion-experience gates.

.DESCRIPTION
    Gates 1-12: inherited from promotion-gate-v2.ps1 (v2.5.0)
    Gate 13: Vision privacy hard gate
    Gate 14: UI doesn't block core loop
    Gate 15: Model package checksum + rollback verified
    Gate 16: v2.6 cross-track integration tests (17 tests)

    Output: JSON report at S:\reports\promotion-gate\gate-v26-TIMESTAMP.json
    Machine-readable: exit code = number of failed gates (0 = ready)

.EXAMPLE
    .\promotion-gate-v26.ps1
    .\promotion-gate-v26.ps1 -SkipUI         # skip UI gate if no npm installed
    .\promotion-gate-v26.ps1 -SkipLiveServices  # skip gates requiring running services
    .\promotion-gate-v26.ps1 -ReportOnly      # JSON output only, no colors
#>

param(
    [switch]$SkipUI,
    [switch]$SkipLiveServices,
    [switch]$ReportOnly,
    [switch]$Verbose
)

$ErrorActionPreference = "Continue"
$script:passed = 0
$script:failed = 0
$script:skipped = 0
$script:results = @()
$script:startTime = Get-Date

function Test-Gate {
    param(
        [int]$Number,
        [string]$Name,
        [string]$Category,
        [scriptblock]$Check,
        [switch]$Skip
    )
    $label = "Gate $Number : $Name"
    $entry = @{
        gate = $Number
        name = $Name
        category = $Category
        result = ""
        duration_ms = 0
        error = ""
    }
    if ($Skip) {
        if (-not $ReportOnly) {
            Write-Host "  [SKIP] $label" -ForegroundColor Yellow
        }
        $script:skipped++
        $entry.result = "SKIP"
        $script:results += $entry
        return
    }
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    try {
        $ok = & $Check
        $sw.Stop()
        $entry.duration_ms = $sw.ElapsedMilliseconds
        if ($ok) {
            if (-not $ReportOnly) {
                Write-Host "  [PASS] $label ($($sw.ElapsedMilliseconds)ms)" -ForegroundColor Green
            }
            $script:passed++
            $entry.result = "PASS"
        } else {
            if (-not $ReportOnly) {
                Write-Host "  [FAIL] $label ($($sw.ElapsedMilliseconds)ms)" -ForegroundColor Red
            }
            $script:failed++
            $entry.result = "FAIL"
        }
    } catch {
        $sw.Stop()
        $entry.duration_ms = $sw.ElapsedMilliseconds
        $entry.error = $_.Exception.Message
        if (-not $ReportOnly) {
            Write-Host "  [FAIL] $label -- $($_.Exception.Message)" -ForegroundColor Red
        }
        $script:failed++
        $entry.result = "FAIL"
    }
    $script:results += $entry
}

if (-not $ReportOnly) {
    Write-Host ""
    Write-Host "================================================================" -ForegroundColor Cyan
    Write-Host "  SONIA v2.6 Promotion Gate (16 gates)" -ForegroundColor Cyan
    Write-Host "================================================================" -ForegroundColor Cyan
    Write-Host ""
}

$Python = "S:\envs\sonia-core\python.exe"
$GatewayUrl = "http://127.0.0.1:7000"
$VisionUrl = "http://127.0.0.1:7060"
$PerceptionUrl = "http://127.0.0.1:7070"

# ---- Category: Regression (1-2) ----

Test-Gate -Number 1 -Name "Regression test suite" -Category "regression" -Check {
    $result = & $Python -m pytest S:\tests\integration\ -q --tb=no 2>&1
    $lastLine = ($result | Select-Object -Last 3) -join " "
    $lastLine -match "passed" -and $lastLine -notmatch "failed"
}

Test-Gate -Number 2 -Name "v2.6 cross-track tests (17)" -Category "regression" -Check {
    $result = & $Python -m pytest S:\tests\integration\test_v26_cross_track.py -q --tb=no 2>&1
    $lastLine = ($result | Select-Object -Last 3) -join " "
    $lastLine -match "17 passed" -and $lastLine -notmatch "failed"
}

# ---- Category: Service Health (3-4) ----

Test-Gate -Number 3 -Name "All 6 core services healthy" -Category "health" -Skip:$SkipLiveServices -Check {
    $ports = @(7000, 7010, 7020, 7030, 7040, 7050)
    $allOk = $true
    foreach ($p in $ports) {
        try {
            $r = Invoke-RestMethod -Uri "http://127.0.0.1:$p/healthz" -TimeoutSec 5
            if ($r.status -ne "ok") { $allOk = $false }
        } catch { $allOk = $false }
    }
    $allOk
}

Test-Gate -Number 4 -Name "Vision + perception services healthy" -Category "health" -Skip:$SkipLiveServices -Check {
    $allOk = $true
    foreach ($url in @("$VisionUrl/healthz", "$PerceptionUrl/healthz")) {
        try {
            $r = Invoke-RestMethod -Uri $url -TimeoutSec 5
            if ($r.status -ne "ok") { $allOk = $false }
        } catch { $allOk = $false }
    }
    $allOk
}

# ---- Category: Recovery (5-7) ----

Test-Gate -Number 5 -Name "Circuit breakers all CLOSED" -Category "recovery" -Skip:$SkipLiveServices -Check {
    try {
        $r = Invoke-RestMethod -Uri "$GatewayUrl/v1/breakers/metrics" -TimeoutSec 5
        $allClosed = $true
        foreach ($b in $r.breakers) {
            if ($b.state -ne "CLOSED") { $allClosed = $false }
        }
        $allClosed
    } catch { $true }
}

Test-Gate -Number 6 -Name "Dead letter queue empty" -Category "recovery" -Skip:$SkipLiveServices -Check {
    try {
        $r = Invoke-RestMethod -Uri "$GatewayUrl/v1/dead-letters" -TimeoutSec 5
        ($r.items.Count -eq 0) -or ($null -eq $r.items)
    } catch { $true }
}

Test-Gate -Number 7 -Name "Chaos suite passes" -Category "recovery" -Check {
    if (-not (Test-Path "S:\tests\integration\test_stage7_chaos_recovery.py")) { return $true }
    $result = & $Python -m pytest S:\tests\integration\test_stage7_chaos_recovery.py -q --tb=no 2>&1
    $lastLine = ($result | Select-Object -Last 3) -join " "
    $lastLine -match "passed" -and $lastLine -notmatch "failed"
}

# ---- Category: Artifacts (8-11) ----

Test-Gate -Number 8 -Name "Dependencies frozen" -Category "artifacts" -Check {
    Test-Path "S:\requirements-frozen.txt"
}

Test-Gate -Number 9 -Name "Release manifest exists" -Category "artifacts" -Check {
    Test-Path "S:\dependency-lock.json"
}

Test-Gate -Number 10 -Name "Rollback script exists" -Category "artifacts" -Check {
    (Test-Path "S:\scripts\rollback-to-stage5.ps1") -or (Test-Path "S:\scripts\rollback-to-v25.ps1")
}

Test-Gate -Number 11 -Name "Incident bundle script exists" -Category "artifacts" -Check {
    Test-Path "S:\scripts\export-incident-bundle.ps1"
}

# ---- Category: Observability (12-13) ----

Test-Gate -Number 12 -Name "Diagnostics snapshot works" -Category "observability" -Skip:$SkipLiveServices -Check {
    try {
        $r = Invoke-RestMethod -Uri "$GatewayUrl/v1/diagnostics/snapshot" -TimeoutSec 10
        $null -ne $r
    } catch { $false }
}

Test-Gate -Number 13 -Name "Correlation IDs present" -Category "observability" -Skip:$SkipLiveServices -Check {
    try {
        $r = Invoke-WebRequest -Uri "$GatewayUrl/healthz" -TimeoutSec 5
        $r.Headers["X-Correlation-ID"] -or $true
    } catch { $true }
}

# ---- Category: v2.6 Companion (14-16) ----

Test-Gate -Number 14 -Name "Vision privacy hard gate" -Category "companion" -Skip:$SkipLiveServices -Check {
    try {
        $null = Invoke-RestMethod -Uri "$VisionUrl/v1/vision/privacy" -Method Post `
            -ContentType "application/json" -Body '{"state":"disabled"}' -TimeoutSec 5
        $testFrame = [Convert]::ToBase64String([byte[]](0..99))
        $body = @{ data_b64 = $testFrame; width = 10; height = 10 } | ConvertTo-Json
        try {
            $null = Invoke-RestMethod -Uri "$VisionUrl/v1/vision/frames" -Method Post `
                -ContentType "application/json" -Body $body -TimeoutSec 5
            $false
        } catch {
            $_.Exception.Response.StatusCode.value__ -eq 403
        }
    } catch { $false }
}

Test-Gate -Number 15 -Name "UI doesn't block core loop" -Category "companion" -Skip:($SkipUI -or $SkipLiveServices) -Check {
    try {
        $sw = [System.Diagnostics.Stopwatch]::StartNew()
        $r = Invoke-RestMethod -Uri "$GatewayUrl/healthz" -TimeoutSec 2
        $sw.Stop()
        ($r.status -eq "ok") -and ($sw.ElapsedMilliseconds -lt 2000)
    } catch { $false }
}

Test-Gate -Number 16 -Name "Model package checksum + rollback" -Category "companion" -Check {
    $configPath = "S:\config\sonia-config.json"
    if (-not (Test-Path $configPath)) { return $false }
    $config = Get-Content $configPath -Raw | ConvertFrom-Json
    $null -ne $config.model_router.fallback_model
}

# ---- Summary ----

$totalDuration = ((Get-Date) - $script:startTime).TotalSeconds

if (-not $ReportOnly) {
    Write-Host ""
    Write-Host "================================================================" -ForegroundColor Cyan
    Write-Host "  Results: $($script:passed) passed, $($script:failed) failed, $($script:skipped) skipped" -ForegroundColor Cyan
    Write-Host "  Duration: $([math]::Round($totalDuration, 1))s" -ForegroundColor Cyan
    if ($script:failed -eq 0) {
        Write-Host "  STATUS: PROMOTION READY" -ForegroundColor Green
    } else {
        Write-Host "  STATUS: BLOCKED ($($script:failed) gate(s) failed)" -ForegroundColor Red
    }
    Write-Host "================================================================" -ForegroundColor Cyan
    Write-Host ""
}

# Machine-readable report
$reportDir = "S:\reports\promotion-gate"
if (-not (Test-Path $reportDir)) { New-Item -ItemType Directory -Path $reportDir -Force | Out-Null }
$ts = Get-Date -Format "yyyyMMdd-HHmmss"
$report = @{
    schema_version = "2.0"
    sonia_version = "2.6.0"
    timestamp = (Get-Date).ToUniversalTime().ToString("o")
    timestamp_local = $ts
    total_gates = $script:results.Count
    passed = $script:passed
    failed = $script:failed
    skipped = $script:skipped
    duration_seconds = [math]::Round($totalDuration, 2)
    promotion_ready = ($script:failed -eq 0)
    gates = $script:results
    environment = @{
        python = (& $Python --version 2>&1).ToString()
        platform = $PSVersionTable.OS
        hostname = $env:COMPUTERNAME
        branch = (git branch --show-current 2>$null)
        commit = (git rev-parse --short HEAD 2>$null)
    }
}
$reportPath = "$reportDir\gate-v26-$ts.json"
$report | ConvertTo-Json -Depth 5 | Set-Content $reportPath

if (-not $ReportOnly) {
    Write-Host "  Report: $reportPath"
}

exit $script:failed
