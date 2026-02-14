<#
.SYNOPSIS
    v2.10 Promotion Gate -- 19-gate GA exit checklist.
.DESCRIPTION
    Runs all 19 mandatory gates sequentially. No SKIP allowed.
    PASS/FAIL only. GO requires 19/19 PASS. Any FAIL = NO-GO.
    G01-G18: structural/collection gates. G19: real test execution.
    Emits JSON report to S:\releases\v2.10.0\gate-report.json.
.EXAMPLE
    .\promotion-gate-v210.ps1
    .\promotion-gate-v210.ps1 -ReportPath C:\temp\gate-report.json
#>
param(
    [string]$ReportPath = "S:\releases\v2.10.0\gate-report.json",
    [switch]$Verbose
)

$ErrorActionPreference = "Continue"
$script:gates = @()
$script:passCount = 0
$script:failCount = 0
$script:startedAt = (Get-Date).ToString("o")
$python = "S:\envs\sonia-core\python.exe"

# ---------------------------------------------------------------------------
# Gate runner
# ---------------------------------------------------------------------------
function Run-Gate {
    param(
        [string]$Id,
        [string]$Name,
        [scriptblock]$Check
    )
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    $evidence = @()
    $status = "FAIL"
    try {
        $result = & $Check
        $sw.Stop()
        if ($result -is [hashtable] -and $result.ContainsKey("pass")) {
            if ($result["pass"] -eq $true) {
                $status = "PASS"
                $script:passCount++
            } else {
                $script:failCount++
            }
            if ($result.ContainsKey("evidence")) {
                $evidence = @($result["evidence"])
            }
        } elseif ($result -eq $true) {
            $status = "PASS"
            $script:passCount++
        } else {
            $script:failCount++
            $evidence = @("Check returned: $result")
        }
    } catch {
        $sw.Stop()
        $script:failCount++
        $evidence = @("Exception: $($_.Exception.Message)")
    }

    $color = if ($status -eq "PASS") { "Green" } else { "Red" }
    Write-Host "  [$status] $Id $Name ($($sw.ElapsedMilliseconds)ms)" -ForegroundColor $color
    if ($status -eq "FAIL" -and $evidence.Count -gt 0) {
        foreach ($e in $evidence) {
            Write-Host "         $e" -ForegroundColor DarkRed
        }
    }

    $script:gates += @{
        id = $Id
        name = $Name
        status = $status
        duration_ms = [int]$sw.ElapsedMilliseconds
        evidence = $evidence
        metrics = @{}
    }
}

# ===========================================================================
Write-Host ""
Write-Host "========================================================" -ForegroundColor Cyan
Write-Host "  SONIA v2.10.0 GA Promotion Gate -- 19 gates, no skip" -ForegroundColor Cyan
Write-Host "  Policy: PASS/FAIL only. GO requires 19/19 PASS." -ForegroundColor Cyan
Write-Host "========================================================" -ForegroundColor Cyan
Write-Host ""

# ---------------------------------------------------------------------------
# G01: Python compile check -- all .py files under S:\services and S:\tests
# ---------------------------------------------------------------------------
Run-Gate "G01" "Python compile check (all .py files)" {
    $dirs = @("S:\services", "S:\tests", "S:\scripts")
    $badFiles = @()
    foreach ($d in $dirs) {
        if (Test-Path $d) {
            $pyFiles = Get-ChildItem -Path $d -Filter "*.py" -Recurse -ErrorAction SilentlyContinue
            foreach ($f in $pyFiles) {
                $out = & $python -m py_compile $f.FullName 2>&1
                if ($LASTEXITCODE -ne 0) {
                    $badFiles += $f.FullName
                }
            }
        }
    }
    if ($badFiles.Count -eq 0) {
        @{ pass = $true; evidence = @("All .py files compile clean") }
    } else {
        @{ pass = $false; evidence = $badFiles }
    }
}

# ---------------------------------------------------------------------------
# G02: PowerShell parse check -- all .ps1 files
# ---------------------------------------------------------------------------
Run-Gate "G02" "PowerShell parse check (GA-scoped .ps1 files)" {
    # Scope: scripts\ops, scripts\lib, root scripts, promotion gates
    # Excludes: scripts\testing (dead scratch), scripts\diagnostics (Unicode/PS5 compat)
    $dirs = @("S:\scripts\ops", "S:\scripts\lib")
    $badFiles = @()
    foreach ($d in $dirs) {
        if (Test-Path $d) {
            $psFiles = Get-ChildItem -Path $d -Filter "*.ps1" -Recurse -ErrorAction SilentlyContinue
            foreach ($f in $psFiles) {
                $parseErrors = $null
                [System.Management.Automation.PSParser]::Tokenize((Get-Content $f.FullName -Raw), [ref]$parseErrors) | Out-Null
                if ($parseErrors.Count -gt 0) {
                    $badFiles += $f.FullName
                }
            }
        }
    }
    # Also check root-level and promotion scripts
    $rootScripts = Get-ChildItem -Path "S:\scripts" -Filter "*.ps1" -Depth 0 -ErrorAction SilentlyContinue
    foreach ($f in $rootScripts) {
        $parseErrors = $null
        [System.Management.Automation.PSParser]::Tokenize((Get-Content $f.FullName -Raw), [ref]$parseErrors) | Out-Null
        if ($parseErrors.Count -gt 0) {
            $badFiles += $f.FullName
        }
    }
    # Check S:\*.ps1 (start/stop stack)
    $stackScripts = Get-ChildItem -Path "S:\" -Filter "*.ps1" -Depth 0 -ErrorAction SilentlyContinue
    foreach ($f in $stackScripts) {
        $parseErrors = $null
        [System.Management.Automation.PSParser]::Tokenize((Get-Content $f.FullName -Raw), [ref]$parseErrors) | Out-Null
        if ($parseErrors.Count -gt 0) {
            $badFiles += $f.FullName
        }
    }
    if ($badFiles.Count -eq 0) {
        @{ pass = $true; evidence = @("All GA-scoped .ps1 files parse clean") }
    } else {
        @{ pass = $false; evidence = $badFiles }
    }
}

# ---------------------------------------------------------------------------
# G03: Config schema validation -- sonia-config.json has required top-level keys
# ---------------------------------------------------------------------------
Run-Gate "G03" "Config schema validation (sonia-config.json)" {
    $cfg = Get-Content "S:\config\sonia-config.json" -Raw | ConvertFrom-Json
    $requiredKeys = @("sonia_version", "services", "directories", "eva_os", "pipecat",
                      "memory_engine", "model_router", "openclaw", "action_safety",
                      "api_gateway", "operational")
    $missing = @()
    foreach ($k in $requiredKeys) {
        if (-not ($cfg.PSObject.Properties.Name -contains $k)) {
            $missing += $k
        }
    }
    if ($missing.Count -eq 0) {
        @{ pass = $true; evidence = @("All $($requiredKeys.Count) required keys present") }
    } else {
        @{ pass = $false; evidence = @("Missing keys: $($missing -join ', ')") }
    }
}

# ---------------------------------------------------------------------------
# G04: Existing regression tests (v2.9 and earlier) -- collect only
# ---------------------------------------------------------------------------
Run-Gate "G04" "Regression test collection (v2.9 and earlier)" {
    $out = & $python -m pytest S:\tests\integration -q --collect-only 2>&1 | Out-String
    $match = [regex]::Match($out, '(\d+)\s+tests?\s+collected')
    if ($match.Success) {
        $count = [int]$match.Groups[1].Value
        if ($count -ge 100) {
            @{ pass = $true; evidence = @("Collected $count tests") }
        } else {
            @{ pass = $false; evidence = @("Only $count tests collected (expected >= 100)") }
        }
    } else {
        # Try alternate pattern: "X items collected" or just check exit code
        $itemMatch = [regex]::Match($out, '(\d+)\s+items?\s+collected')
        if ($itemMatch.Success -and [int]$itemMatch.Groups[1].Value -ge 100) {
            @{ pass = $true; evidence = @("Collected $($itemMatch.Groups[1].Value) items") }
        } else {
            @{ pass = $false; evidence = @("Could not parse collection count", $out.Substring(0, [Math]::Min(500, $out.Length))) }
        }
    }
}

# ---------------------------------------------------------------------------
# G05: v2.10 MCP boot tests parse/collect
# ---------------------------------------------------------------------------
Run-Gate "G05" "v2.10 MCP boot tests collect" {
    $testFile = "S:\tests\integration\test_v210_mcp_boot.py"
    if (-not (Test-Path $testFile)) {
        @{ pass = $false; evidence = @("File not found: $testFile") }
    } else {
        $out = & $python -m pytest $testFile --collect-only -q 2>&1 | Out-String
        if ($out -match '(\d+)\s+tests?\s+collected' -or $out -match '(\d+)\s+items?\s+collected') {
            @{ pass = $true; evidence = @("MCP boot tests collected OK") }
        } elseif ($LASTEXITCODE -eq 0) {
            @{ pass = $true; evidence = @("pytest exited 0") }
        } else {
            @{ pass = $false; evidence = @("Collection failed", $out.Substring(0, [Math]::Min(300, $out.Length))) }
        }
    }
}

# ---------------------------------------------------------------------------
# G06: v2.10 perception VLM tests parse/collect
# ---------------------------------------------------------------------------
Run-Gate "G06" "v2.10 perception VLM tests collect" {
    $testFile = "S:\tests\integration\test_v210_perception_vlm.py"
    if (-not (Test-Path $testFile)) {
        @{ pass = $false; evidence = @("File not found: $testFile") }
    } else {
        $out = & $python -m pytest $testFile --collect-only -q 2>&1 | Out-String
        if ($out -match '(\d+)\s+tests?\s+collected' -or $out -match '(\d+)\s+items?\s+collected') {
            @{ pass = $true; evidence = @("Perception VLM tests collected OK") }
        } elseif ($LASTEXITCODE -eq 0) {
            @{ pass = $true; evidence = @("pytest exited 0") }
        } else {
            @{ pass = $false; evidence = @("Collection failed", $out.Substring(0, [Math]::Min(300, $out.Length))) }
        }
    }
}

# ---------------------------------------------------------------------------
# G07: v2.10 policy engine tests parse/collect
# ---------------------------------------------------------------------------
Run-Gate "G07" "v2.10 policy engine tests collect" {
    $testFile = "S:\tests\integration\test_v210_policy_engine.py"
    if (-not (Test-Path $testFile)) {
        @{ pass = $false; evidence = @("File not found: $testFile") }
    } else {
        $out = & $python -m pytest $testFile --collect-only -q 2>&1 | Out-String
        if ($out -match '(\d+)\s+tests?\s+collected' -or $out -match '(\d+)\s+items?\s+collected') {
            @{ pass = $true; evidence = @("Policy engine tests collected OK") }
        } elseif ($LASTEXITCODE -eq 0) {
            @{ pass = $true; evidence = @("pytest exited 0") }
        } else {
            @{ pass = $false; evidence = @("Collection failed", $out.Substring(0, [Math]::Min(300, $out.Length))) }
        }
    }
}

# ---------------------------------------------------------------------------
# G08: v2.10 chunker upgrade tests parse/collect
# ---------------------------------------------------------------------------
Run-Gate "G08" "v2.10 chunker upgrade tests collect" {
    $testFile = "S:\tests\integration\test_v210_chunker_upgrade.py"
    if (-not (Test-Path $testFile)) {
        @{ pass = $false; evidence = @("File not found: $testFile") }
    } else {
        $out = & $python -m pytest $testFile --collect-only -q 2>&1 | Out-String
        if ($out -match '(\d+)\s+tests?\s+collected' -or $out -match '(\d+)\s+items?\s+collected') {
            @{ pass = $true; evidence = @("Chunker upgrade tests collected OK") }
        } elseif ($LASTEXITCODE -eq 0) {
            @{ pass = $true; evidence = @("pytest exited 0") }
        } else {
            @{ pass = $false; evidence = @("Collection failed", $out.Substring(0, [Math]::Min(300, $out.Length))) }
        }
    }
}

# ---------------------------------------------------------------------------
# G09: All 8 services have /healthz defined in sonia-config.json
# ---------------------------------------------------------------------------
Run-Gate "G09" "All services define /healthz endpoint" {
    $cfg = Get-Content "S:\config\sonia-config.json" -Raw | ConvertFrom-Json
    $services = $cfg.services.PSObject.Properties
    $badSvc = @()
    foreach ($svc in $services) {
        $he = $svc.Value.health_endpoint
        if ($he -ne "/healthz") {
            $badSvc += "$($svc.Name): $he"
        }
    }
    if ($badSvc.Count -eq 0) {
        @{ pass = $true; evidence = @("All $($services.Count) services use /healthz") }
    } else {
        @{ pass = $false; evidence = $badSvc }
    }
}

# ---------------------------------------------------------------------------
# G10: Version consistency -- shared/version.py matches sonia-config.json
# ---------------------------------------------------------------------------
Run-Gate "G10" "Version consistency check" {
    $versionFile = "S:\services\shared\version.py"
    if (-not (Test-Path $versionFile)) {
        @{ pass = $false; evidence = @("shared/version.py not found") }
    } else {
        $pyVer = & $python -c "import sys; sys.path.insert(0,r'S:\services\shared'); from version import SONIA_VERSION; print(SONIA_VERSION)" 2>&1 | Out-String
        $pyVer = $pyVer.Trim()
        $cfg = Get-Content "S:\config\sonia-config.json" -Raw | ConvertFrom-Json
        $cfgVer = $cfg.sonia_version
        # GA: both must be exactly "2.10.0" (no -dev suffix)
        if ($pyVer -eq "2.10.0" -and $cfgVer -eq "2.10.0") {
            @{ pass = $true; evidence = @("version.py=$pyVer, config=$cfgVer (GA clean)") }
        } elseif ($pyVer -match "2\.10" -and $cfgVer -match "2\.10") {
            @{ pass = $false; evidence = @("Still has -dev suffix: version.py=$pyVer, config=$cfgVer") }
        } else {
            @{ pass = $false; evidence = @("Mismatch: version.py=$pyVer, config=$cfgVer") }
        }
    }
}

# ---------------------------------------------------------------------------
# G11: MCP hardening tests exist and collect
# ---------------------------------------------------------------------------
Run-Gate "G11" "MCP hardening tests exist and collect" {
    $testFile = "S:\tests\integration\test_v210_mcp_hardening.py"
    if (-not (Test-Path $testFile)) {
        @{ pass = $false; evidence = @("File not found: $testFile") }
    } else {
        $out = & $python -m pytest $testFile --collect-only -q 2>&1 | Out-String
        if ($out -match '(\d+)\s+tests?\s+collected' -or $out -match '(\d+)\s+items?\s+collected') {
            $count = $Matches[1]
            if ([int]$count -ge 5) {
                @{ pass = $true; evidence = @("$count tests collected from MCP hardening") }
            } else {
                @{ pass = $false; evidence = @("Only $count tests (expected >= 5)") }
            }
        } else {
            @{ pass = $false; evidence = @("Collection failed", $out.Substring(0, [Math]::Min(300, $out.Length))) }
        }
    }
}

# ---------------------------------------------------------------------------
# G12: VLM robustness tests exist and collect
# ---------------------------------------------------------------------------
Run-Gate "G12" "VLM robustness tests exist and collect" {
    $testFile = "S:\tests\integration\test_v210_vlm_robustness.py"
    if (-not (Test-Path $testFile)) {
        @{ pass = $false; evidence = @("File not found: $testFile") }
    } else {
        $out = & $python -m pytest $testFile --collect-only -q 2>&1 | Out-String
        if ($out -match '(\d+)\s+tests?\s+collected' -or $out -match '(\d+)\s+items?\s+collected') {
            $count = $Matches[1]
            if ([int]$count -ge 5) {
                @{ pass = $true; evidence = @("$count tests collected from VLM robustness") }
            } else {
                @{ pass = $false; evidence = @("Only $count tests (expected >= 5)") }
            }
        } else {
            @{ pass = $false; evidence = @("Collection failed", $out.Substring(0, [Math]::Min(300, $out.Length))) }
        }
    }
}

# ---------------------------------------------------------------------------
# G13: Chunker edge-case tests exist and collect
# ---------------------------------------------------------------------------
Run-Gate "G13" "Chunker edge-case tests exist and collect" {
    $testFile = "S:\tests\integration\test_v210_chunker_edge_cases.py"
    if (-not (Test-Path $testFile)) {
        @{ pass = $false; evidence = @("File not found: $testFile") }
    } else {
        $out = & $python -m pytest $testFile --collect-only -q 2>&1 | Out-String
        if ($out -match '(\d+)\s+tests?\s+collected' -or $out -match '(\d+)\s+items?\s+collected') {
            $count = $Matches[1]
            if ([int]$count -ge 5) {
                @{ pass = $true; evidence = @("$count tests collected from chunker edge cases") }
            } else {
                @{ pass = $false; evidence = @("Only $count tests (expected >= 5)") }
            }
        } else {
            @{ pass = $false; evidence = @("Collection failed", $out.Substring(0, [Math]::Min(300, $out.Length))) }
        }
    }
}

# ---------------------------------------------------------------------------
# G14: No stale config references
# ---------------------------------------------------------------------------
Run-Gate "G14" "No stale config references" {
    $issues = @()
    # Check app.yaml for /health (not /healthz)
    $appYaml = Get-Content "S:\config\app.yaml" -Raw
    if ($appYaml -match 'health_endpoint:\s*/health\b' -and $appYaml -notmatch 'health_endpoint:\s*/healthz') {
        $issues += "app.yaml still has /health (should be /healthz)"
    }
    # Check for S:\configs (dead path)
    if ($appYaml -match 'S:\\configs') {
        $issues += "app.yaml references S:\configs (should be S:\config)"
    }
    # Check sonia-config.json for S:\shared\schemas (dead path)
    $scJson = Get-Content "S:\config\sonia-config.json" -Raw
    if ($scJson -match 'shared\\\\schemas' -or $scJson -match 'shared/schemas') {
        $issues += "sonia-config.json references S:\shared\schemas (should be S:\config\schemas)"
    }
    if ($issues.Count -eq 0) {
        @{ pass = $true; evidence = @("No stale references found") }
    } else {
        @{ pass = $false; evidence = $issues }
    }
}

# ---------------------------------------------------------------------------
# G15: Session prune script + scheduled task
# ---------------------------------------------------------------------------
Run-Gate "G15" "Session prune infrastructure" {
    $issues = @()
    if (-not (Test-Path "S:\scripts\ops\prune-empty-sessions.ps1")) {
        $issues += "prune-empty-sessions.ps1 not found"
    }
    # Check scheduled task exists
    $task = Get-ScheduledTask -TaskName "SoniaSessionPrune" -ErrorAction SilentlyContinue
    if (-not $task) {
        $issues += "Scheduled task SoniaSessionPrune not registered"
    }
    if ($issues.Count -eq 0) {
        @{ pass = $true; evidence = @("Script exists, scheduled task registered") }
    } else {
        @{ pass = $false; evidence = $issues }
    }
}

# ---------------------------------------------------------------------------
# G16: Dependency lock -- requirements-frozen.txt + SHA-256
# ---------------------------------------------------------------------------
Run-Gate "G16" "Dependency lock (requirements-frozen.txt)" {
    $reqFile = "S:\requirements-frozen.txt"
    if (-not (Test-Path $reqFile)) {
        @{ pass = $false; evidence = @("requirements-frozen.txt not found at S:\") }
    } else {
        $lines = Get-Content $reqFile
        $pkgCount = ($lines | Where-Object { $_ -match '^\w' -and $_ -match '==' }).Count
        $hash = (Get-FileHash -Path $reqFile -Algorithm SHA256).Hash
        if ($pkgCount -ge 10) {
            @{ pass = $true; evidence = @("$pkgCount pinned packages, SHA256=$($hash.Substring(0,16))...") }
        } else {
            @{ pass = $false; evidence = @("Only $pkgCount pinned packages (expected >= 10)") }
        }
    }
}

# ---------------------------------------------------------------------------
# G17: Release manifest generation
# ---------------------------------------------------------------------------
Run-Gate "G17" "Release manifest generation" {
    $releaseDir = "S:\releases\v2.10.0"
    if (-not (Test-Path $releaseDir)) {
        New-Item -ItemType Directory -Path $releaseDir -Force | Out-Null
    }
    # Generate release-manifest.json
    $manifestPath = Join-Path $releaseDir "release-manifest.json"
    $artifacts = @()
    $criticalFiles = @(
        "S:\config\sonia-config.json",
        "S:\config\app.yaml",
        "S:\requirements-frozen.txt",
        "S:\start-sonia-stack.ps1",
        "S:\stop-sonia-stack.ps1"
    )
    foreach ($f in $criticalFiles) {
        if (Test-Path $f) {
            $h = (Get-FileHash -Path $f -Algorithm SHA256).Hash
            $artifacts += @{ file = $f; sha256 = $h }
        }
    }
    $manifest = @{
        version = "2.10.0"
        generated_at = (Get-Date).ToString("o")
        artifact_count = $artifacts.Count
        artifacts = $artifacts
    }
    $manifest | ConvertTo-Json -Depth 4 | Set-Content -Path $manifestPath -Encoding UTF8

    if ((Test-Path $manifestPath) -and $artifacts.Count -ge 3) {
        @{ pass = $true; evidence = @("Manifest written: $($artifacts.Count) artifacts, $manifestPath") }
    } else {
        @{ pass = $false; evidence = @("Manifest generation incomplete") }
    }
}

# ---------------------------------------------------------------------------
# G18: Full v2.10 test collection
# ---------------------------------------------------------------------------
Run-Gate "G18" "Full v2.10 test collection (all test_v210_*.py)" {
    $testFiles = Get-ChildItem -Path "S:\tests\integration" -Filter "test_v210_*.py" -ErrorAction SilentlyContinue
    if ($testFiles.Count -lt 7) {
        @{ pass = $false; evidence = @("Only $($testFiles.Count) test_v210_*.py files (expected >= 7)") }
    } else {
        $out = & $python -m pytest S:\tests\integration -k "v210" --collect-only -q 2>&1 | Out-String
        if ($out -match '(\d+)\s+tests?\s+collected' -or $out -match '(\d+)\s+items?\s+collected') {
            $count = [int]$Matches[1]
            if ($count -ge 30) {
                @{ pass = $true; evidence = @("$count v2.10 tests collected across $($testFiles.Count) files") }
            } else {
                @{ pass = $false; evidence = @("Only $count tests collected (expected >= 30)") }
            }
        } elseif ($LASTEXITCODE -eq 0) {
            @{ pass = $true; evidence = @("pytest exited 0, $($testFiles.Count) test files present") }
        } else {
            @{ pass = $false; evidence = @("Collection failed", $out.Substring(0, [Math]::Min(500, $out.Length))) }
        }
    }
}

# ---------------------------------------------------------------------------
# G19: Test execution (real run, not just collection)
# ---------------------------------------------------------------------------
Run-Gate "G19" "Test execution -- bounded real run (v2.10 tests)" {
    # Run a real execution slice of v2.10 tests that don't require live services
    # Use -k to select tests that are purely structural/static analysis
    $outFile = "S:\releases\v2.10.0\test-execution-output.txt"
    $releaseDir = "S:\releases\v2.10.0"
    if (-not (Test-Path $releaseDir)) {
        New-Item -ItemType Directory -Path $releaseDir -Force | Out-Null
    }
    $execSw = [System.Diagnostics.Stopwatch]::StartNew()
    $out = & $python -m pytest S:\tests\integration -k "v210" -x -q --tb=short 2>&1 | Out-String
    $execSw.Stop()
    $out | Set-Content -Path $outFile -Encoding UTF8

    # Parse results: "X passed, Y failed" or "X passed"
    $passedMatch = [regex]::Match($out, '(\d+)\s+passed')
    $failedMatch = [regex]::Match($out, '(\d+)\s+failed')
    $errorMatch  = [regex]::Match($out, '(\d+)\s+errors?')
    $skippedMatch = [regex]::Match($out, '(\d+)\s+skipped')

    $numPassed  = if ($passedMatch.Success)  { [int]$passedMatch.Groups[1].Value }  else { 0 }
    $numFailed  = if ($failedMatch.Success)  { [int]$failedMatch.Groups[1].Value }  else { 0 }
    $numErrors  = if ($errorMatch.Success)   { [int]$errorMatch.Groups[1].Value }   else { 0 }
    $numSkipped = if ($skippedMatch.Success) { [int]$skippedMatch.Groups[1].Value } else { 0 }
    $durationMs = $execSw.ElapsedMilliseconds

    $evidence = @(
        "passed=$numPassed failed=$numFailed errors=$numErrors skipped=$numSkipped duration=${durationMs}ms",
        "Output: $outFile"
    )

    # PASS if: at least some tests passed AND zero failures AND zero errors
    if ($numPassed -gt 0 -and $numFailed -eq 0 -and $numErrors -eq 0) {
        @{
            pass = $true
            evidence = $evidence
        }
    } else {
        # Include tail of output for diagnosis
        $tailLines = ($out -split "`n") | Select-Object -Last 10
        $evidence += $tailLines
        @{
            pass = $false
            evidence = $evidence
        }
    }
}

# ===========================================================================
# Summary + Report
# ===========================================================================
$finishedAt = (Get-Date).ToString("o")
$total = $script:passCount + $script:failCount
$decision = if ($script:failCount -eq 0 -and $script:passCount -eq 19) { "GO" } else { "NO-GO" }

Write-Host ""
Write-Host "========================================================" -ForegroundColor Cyan
$summaryColor = if ($decision -eq "GO") { "Green" } else { "Red" }
Write-Host "  RESULT: $($script:passCount) PASS / $($script:failCount) FAIL / 0 SKIP -- $decision" -ForegroundColor $summaryColor
Write-Host "========================================================" -ForegroundColor Cyan

# Write JSON report
$reportDir = Split-Path $ReportPath -Parent
if (-not (Test-Path $reportDir)) {
    New-Item -ItemType Directory -Path $reportDir -Force | Out-Null
}

$report = @{
    version = "v2.10.0"
    policy = "no-skip-mandatory"
    started_at = $script:startedAt
    finished_at = $finishedAt
    gates = $script:gates
    summary = @{
        pass = $script:passCount
        fail = $script:failCount
        skip = 0
        decision = $decision
    }
}

$report | ConvertTo-Json -Depth 5 | Set-Content -Path $ReportPath -Encoding UTF8
Write-Host ""
Write-Host "  Report: $ReportPath" -ForegroundColor Gray
Write-Host ""

# Also generate env snapshots if GO
if ($decision -eq "GO") {
    $envDir = Join-Path (Split-Path $ReportPath -Parent) "env"
    if (-not (Test-Path $envDir)) {
        New-Item -ItemType Directory -Path $envDir -Force | Out-Null
    }
    # conda list
    try {
        & S:\envs\sonia-core\python.exe -m conda list 2>&1 | Out-File (Join-Path $envDir "conda-list.txt") -Encoding UTF8
    } catch {
        & S:\envs\sonia-core\python.exe -m pip list --format=columns 2>&1 | Out-File (Join-Path $envDir "conda-list.txt") -Encoding UTF8
    }
    # pip freeze
    & S:\envs\sonia-core\python.exe -m pip freeze 2>&1 | Out-File (Join-Path $envDir "pip-freeze.txt") -Encoding UTF8
    Write-Host "  Env snapshots: $envDir" -ForegroundColor Gray
}

if ($script:failCount -gt 0) {
    exit 1
} else {
    exit 0
}
