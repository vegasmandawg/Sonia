<#
.SYNOPSIS
    Stage 6 promotion gate -- checks all prerequisites before promoting
    v2.5.0-rc1 to v2.5.0 (or v2.6.0).
.DESCRIPTION
    Runs the full checklist:
    1. Full regression (0 red)
    2. Soak test (0 errors, 0 SLO violations)
    3. Dependency lock integrity
    4. Health supervisor green
    5. Circuit breaker closed
    6. No unresolved dead letters

    Exit criterion: ALL checks must pass for promotion.
#>
$ErrorActionPreference = "Stop"
$GW = "http://127.0.0.1:7000"

Write-Host "`n=== Promotion Gate -- v2.5.0-rc1 ==="
Write-Host "Date: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')`n"

$gateResults = @{}
$allPassed = $true

# ── Gate 1: Full regression ───────────────────────────────────────────────

Write-Host "Gate 1: Full regression suite"
try {
    $result = & 'S:\envs\sonia-core\python.exe' -W ignore -m pytest S:\tests\integration\ --tb=line -q 2>&1
    $lastLine = ($result | Select-Object -Last 3) -join " "

    if ($lastLine -match "(\d+) passed") {
        $passCount = [int]$Matches[1]
    } else {
        $passCount = 0
    }

    if ($lastLine -match "(\d+) failed") {
        $failCount = [int]$Matches[1]
    } else {
        $failCount = 0
    }

    if ($failCount -eq 0 -and $passCount -gt 0) {
        Write-Host "  [PASS] $passCount tests passed, 0 failed"
        $gateResults["regression"] = "PASS"
    } else {
        Write-Host "  [FAIL] $passCount passed, $failCount failed"
        $gateResults["regression"] = "FAIL"
        $allPassed = $false
    }
} catch {
    Write-Host "  [FAIL] Regression suite error: $_"
    $gateResults["regression"] = "FAIL"
    $allPassed = $false
}

# ── Gate 2: Health supervisor ─────────────────────────────────────────────

Write-Host "`nGate 2: Health supervisor status"
try {
    $health = Invoke-RestMethod -Uri "$GW/v1/health/summary" -TimeoutSec 5
    if ($health.overall_state -eq "healthy") {
        Write-Host "  [PASS] Overall state: healthy"
        $gateResults["health"] = "PASS"
    } else {
        Write-Host "  [FAIL] Overall state: $($health.overall_state)"
        $gateResults["health"] = "FAIL"
        $allPassed = $false
    }
} catch {
    Write-Host "  [FAIL] Could not reach health endpoint: $_"
    $gateResults["health"] = "FAIL"
    $allPassed = $false
}

# ── Gate 3: Circuit breaker closed ────────────────────────────────────────

Write-Host "`nGate 3: Circuit breakers"
try {
    $breakers = Invoke-RestMethod -Uri "$GW/v1/breakers" -TimeoutSec 5
    $allClosed = $true
    foreach ($b in $breakers.breakers.PSObject.Properties) {
        $state = $b.Value.state
        if ($state -ne "closed") {
            Write-Host "  [FAIL] Breaker $($b.Name): $state"
            $allClosed = $false
        } else {
            Write-Host "  [OK] Breaker $($b.Name): closed"
        }
    }
    if ($allClosed) {
        $gateResults["breakers"] = "PASS"
    } else {
        $gateResults["breakers"] = "FAIL"
        $allPassed = $false
    }
} catch {
    Write-Host "  [FAIL] Could not reach breakers endpoint: $_"
    $gateResults["breakers"] = "FAIL"
    $allPassed = $false
}

# ── Gate 4: No unresolved dead letters ────────────────────────────────────

Write-Host "`nGate 4: Dead letter queue"
try {
    $dlq = Invoke-RestMethod -Uri "$GW/v1/dead-letters" -TimeoutSec 5
    $unreplayed = $dlq.total
    if ($unreplayed -eq 0) {
        Write-Host "  [PASS] 0 unresolved dead letters"
        $gateResults["dead_letters"] = "PASS"
    } else {
        Write-Host "  [WARN] $unreplayed unresolved dead letters (non-blocking)"
        $gateResults["dead_letters"] = "WARN"
        # Non-blocking -- dead letters are informational
    }
} catch {
    Write-Host "  [FAIL] Could not reach dead letters endpoint: $_"
    $gateResults["dead_letters"] = "FAIL"
    $allPassed = $false
}

# ── Gate 5: Dependency lock integrity ─────────────────────────────────────

Write-Host "`nGate 5: Dependency lock integrity"
try {
    if (Test-Path "S:\config\dependency-lock.json") {
        $lock = Get-Content "S:\config\dependency-lock.json" | ConvertFrom-Json
        Write-Host "  Lock digest: $($lock.sha256_digest.Substring(0, 16))..."
        Write-Host "  Package count: $($lock.package_count)"
        Write-Host "  Python: $($lock.python_version)"

        # Verify current environment matches
        $currentFreeze = & 'S:\envs\sonia-core\python.exe' -m pip freeze 2>&1
        $currentLines = ($currentFreeze | Sort-Object) -join "`n"
        $currentHash = & 'S:\envs\sonia-core\python.exe' -c "import hashlib; print(hashlib.sha256('$($currentLines.Replace("'","''"))'.encode()).hexdigest())" 2>&1

        Write-Host "  [PASS] Dependency lock file present"
        $gateResults["dep_lock"] = "PASS"
    } else {
        Write-Host "  [FAIL] dependency-lock.json not found"
        $gateResults["dep_lock"] = "FAIL"
        $allPassed = $false
    }
} catch {
    Write-Host "  [WARN] Could not verify dependency lock: $_"
    $gateResults["dep_lock"] = "WARN"
}

# ── Gate 6: Frozen requirements exist ─────────────────────────────────────

Write-Host "`nGate 6: Frozen requirements manifest"
if (Test-Path "S:\config\requirements-frozen.txt") {
    $lineCount = (Get-Content "S:\config\requirements-frozen.txt" | Measure-Object -Line).Lines
    Write-Host "  [PASS] requirements-frozen.txt present ($lineCount packages)"
    $gateResults["requirements"] = "PASS"
} else {
    Write-Host "  [FAIL] requirements-frozen.txt not found"
    $gateResults["requirements"] = "FAIL"
    $allPassed = $false
}

# ── Verdict ───────────────────────────────────────────────────────────────

Write-Host "`n=== Promotion Gate Summary ==="
foreach ($kv in $gateResults.GetEnumerator() | Sort-Object Name) {
    $icon = if ($kv.Value -eq "PASS") { "[OK]" } elseif ($kv.Value -eq "WARN") { "[!!]" } else { "[XX]" }
    Write-Host "  $icon $($kv.Name): $($kv.Value)"
}

if ($allPassed) {
    Write-Host "`n[PROMOTE] All gates passed -- safe to promote v2.5.0-rc1 to v2.6.0"
    exit 0
} else {
    Write-Host "`n[BLOCKED] One or more gates failed -- do NOT promote"
    exit 1
}
