<#
.SYNOPSIS
    v2.9 Promotion Gate -- System Closure verification checklist
.DESCRIPTION
    Validates all v2.9 closures: provider parity, EVA supervision,
    hybrid memory, lifecycle migration, version consistency,
    dependency dedup, and artifact hygiene.
#>
param(
    [switch]$Verbose,
    [string]$ReportPath = "S:\releases\v2.9.0\gate-report.json"
)

$ErrorActionPreference = "Continue"
$script:results = @()
$script:passed = 0
$script:failed = 0
$script:skipped = 0

function Run-Gate {
    param([string]$Name, [scriptblock]$Check)
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    try {
        $result = & $Check
        $sw.Stop()
        if ($result -eq $true) {
            $script:passed++
            $status = "PASS"
            Write-Host "  [PASS] $Name ($($sw.ElapsedMilliseconds)ms)" -ForegroundColor Green
        } else {
            $script:failed++
            $status = "FAIL"
            Write-Host "  [FAIL] $Name ($($sw.ElapsedMilliseconds)ms)" -ForegroundColor Red
        }
    } catch {
        $sw.Stop()
        $script:failed++
        $status = "FAIL"
        Write-Host "  [FAIL] $Name -- $($_.Exception.Message)" -ForegroundColor Red
    }
    $script:results += @{
        gate = $Name
        status = $status
        duration_ms = $sw.ElapsedMilliseconds
    }
}

Write-Host ""
Write-Host "=====================================" -ForegroundColor Cyan
Write-Host "  v2.9 Promotion Gate -- System Closure" -ForegroundColor Cyan
Write-Host "=====================================" -ForegroundColor Cyan
Write-Host ""

# --- Gate 1: v2.9 Model Routing Tests ---
Run-Gate "Provider parity tests" {
    $out = & S:\envs\sonia-core\python.exe -m pytest S:\tests\integration\test_v29_model_routing.py -q 2>&1
    $out -match "passed" -and $out -notmatch "failed"
}

# --- Gate 2: EVA Supervision Tests ---
Run-Gate "EVA supervision tests" {
    $out = & S:\envs\sonia-core\python.exe -m pytest S:\tests\integration\test_v29_eva_supervision.py -q 2>&1
    $out -match "passed" -and $out -notmatch "failed"
}

# --- Gate 3: Memory Hybrid Search Tests ---
Run-Gate "Memory hybrid search tests" {
    $out = & S:\envs\sonia-core\python.exe -m pytest S:\tests\integration\test_v29_memory_hybrid.py -q 2>&1
    $out -match "passed" -and $out -notmatch "failed"
}

# --- Gate 4: Version consistency ---
Run-Gate "Version consistency (shared/version.py)" {
    $ver = & S:\envs\sonia-core\python.exe -c "import sys; sys.path.insert(0,r'S:\services\shared'); from version import SONIA_VERSION; print(SONIA_VERSION)" 2>&1
    $ver.Trim() -eq "2.9.0"
}

# --- Gate 5: No duplicate requirements-frozen ---
Run-Gate "Single requirements-frozen.txt" {
    -not (Test-Path "S:\config\requirements-frozen.txt") -and (Test-Path "S:\requirements-frozen.txt")
}

# --- Gate 6: No @app.on_event in core services ---
Run-Gate "No deprecated on_event in core services" {
    $hits = @()
    $coreServices = @(
        "S:\services\api-gateway\main.py",
        "S:\services\model-router\main.py",
        "S:\services\memory-engine\main.py",
        "S:\services\openclaw\main.py",
        "S:\services\pipecat\main.py",
        "S:\services\eva-os\main.py"
    )
    foreach ($f in $coreServices) {
        $content = Get-Content $f -Raw
        if ($content -match '@app\.on_event') {
            $hits += $f
        }
    }
    $hits.Count -eq 0
}

# --- Gate 7: Provider stubs removed ---
Run-Gate "No not_implemented stubs in providers.py" {
    $content = Get-Content "S:\services\model-router\providers.py" -Raw
    -not ($content -match '"not_implemented"')
}

# --- Gate 8: EVA-OS no hardcoded health ---
Run-Gate "EVA-OS uses real supervision" {
    $content = Get-Content "S:\services\eva-os\main.py" -Raw
    ($content -match 'ServiceSupervisor') -and ($content -match 'probe_all')
}

# --- Gate 9: Memory engine hybrid search wired ---
Run-Gate "Memory engine hybrid search active" {
    $content = Get-Content "S:\services\memory-engine\main.py" -Raw
    ($content -match 'HybridSearchLayer') -and ($content -match '/v1/search')
}

# --- Gate 10: Provenance tracking active ---
Run-Gate "Provenance tracker wired" {
    $content = Get-Content "S:\services\memory-engine\main.py" -Raw
    ($content -match 'ProvenanceTracker') -and ($content -match '/v1/provenance')
}

# --- Gate 11: Gitignore covers test artifacts ---
Run-Gate "Gitignore covers test artifacts" {
    $gi = Get-Content "S:\.gitignore" -Raw
    ($gi -match 'tests/\*\.txt') -and ($gi -match 'DumpStack')
}

# --- Gate 12: shared/version.py exists ---
Run-Gate "Shared version module exists" {
    Test-Path "S:\services\shared\version.py"
}

# --- Summary ---
Write-Host ""
Write-Host "=====================================" -ForegroundColor Cyan
$total = $script:passed + $script:failed + $script:skipped
Write-Host "  Results: $($script:passed) passed, $($script:failed) failed, $($script:skipped) skipped / $total total" -ForegroundColor $(if ($script:failed -eq 0) { "Green" } else { "Red" })
Write-Host "=====================================" -ForegroundColor Cyan

# --- Write JSON report ---
$reportDir = Split-Path $ReportPath -Parent
if (-not (Test-Path $reportDir)) {
    New-Item -ItemType Directory -Path $reportDir -Force | Out-Null
}

$report = @{
    version = "2.9.0"
    timestamp = (Get-Date -Format "o")
    passed = $script:passed
    failed = $script:failed
    skipped = $script:skipped
    total = $total
    gates = $script:results
} | ConvertTo-Json -Depth 3

Set-Content -Path $ReportPath -Value $report -Encoding UTF8
Write-Host ""
Write-Host "  Report: $ReportPath" -ForegroundColor Gray

if ($script:failed -gt 0) {
    exit 1
}
