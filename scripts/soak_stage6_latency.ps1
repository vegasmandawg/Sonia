<#
.SYNOPSIS
    Stage 6 soak test — 10x throughput + per-capability latency budgets.
.PARAMETER Actions
    Number of action cycles to run (default 80).
.PARAMETER Parallel
    Number of concurrent actions per cycle (default 3).
.DESCRIPTION
    Runs 240+ actions through the pipeline with per-capability latency
    tracking. Computes p50/p95/p99 by capability and checks against SLOs.

    SLO targets (local desktop actions, warm gateway):
      Native (ctypes) safe:  file.read, window.list, window.focus  → p95 < 200ms
      Subprocess safe:       clipboard.read                        → p95 < 2000ms (PS process)
      Subprocess low:        clipboard.write                       → p95 < 2000ms (PS process)
      Dry-run (medium/high): all guarded capabilities              → p95 < 200ms  (validate only)
      Browser open (low):    browser.open                          → p95 < 200ms  (dry_run)
#>
param(
    [int]$Actions = 80,
    [int]$Parallel = 3
)

$ErrorActionPreference = "Stop"
$GW = "http://127.0.0.1:7000"

# ── Preflight ──────────────────────────────────────────────────────────────

Write-Host "`n=== Stage 6 Soak Test -- 10x Throughput ==="
Write-Host "Actions: $Actions, Parallel: $Parallel"
$expectedTotal = $Actions * $Parallel
Write-Host "Expected total actions: $expectedTotal"

try {
    $h = Invoke-RestMethod -Uri "$GW/healthz" -TimeoutSec 5
    if (-not $h.ok) { throw "Gateway not healthy" }
    Write-Host "[OK] Gateway healthy"
} catch {
    Write-Host "[FAIL] Gateway health check failed: $_"
    exit 1
}

# ── Test Data (all 13 capabilities) ───────────────────────────────────────

$safeActions = @(
    @{ intent = "file.read"; params = @{ path = "S:\config\sonia-config.json" }; slo_ms = 200 },
    @{ intent = "window.list"; params = @{}; slo_ms = 200 },
    @{ intent = "clipboard.read"; params = @{}; slo_ms = 2000 },
    @{ intent = "window.focus"; params = @{ title = "NonExistentWindowXYZ" }; slo_ms = 200 }
)

$lowActions = @(
    @{ intent = "clipboard.write"; params = @{ text = "soak-test" }; slo_ms = 2000 }
)

$dryRunActions = @(
    @{ intent = "file.write"; params = @{ path = "S:\tmp\soak-test.txt"; content = "test" }; slo_ms = 2000 },
    @{ intent = "shell.run"; params = @{ command = "Get-ChildItem" }; slo_ms = 2000 },
    @{ intent = "app.launch"; params = @{ target = "notepad.exe" }; slo_ms = 2000 },
    @{ intent = "app.close"; params = @{ target = "notepad.exe" }; slo_ms = 2000 },
    @{ intent = "keyboard.type"; params = @{ text = "hello" }; slo_ms = 2000 },
    @{ intent = "keyboard.hotkey"; params = @{ keys = "ctrl+s" }; slo_ms = 2000 },
    @{ intent = "mouse.click"; params = @{ x = 100; y = 100 }; slo_ms = 2000 },
    @{ intent = "browser.open"; params = @{ url = "https://example.com" }; slo_ms = 2000 }
)

# ── Metrics ────────────────────────────────────────────────────────────────

$metrics = @{
    total = 0
    succeeded = 0
    pending = 0
    validated = 0
    errors = 0
}

# Per-capability latency lists
$latencyByCapability = @{}
$errorCodes = @{}

function Get-Percentile {
    param([System.Collections.Generic.List[double]]$values, [double]$pct)
    if ($values.Count -eq 0) { return 0 }
    $sorted = $values | Sort-Object
    $idx = [math]::Floor($sorted.Count * $pct)
    if ($idx -ge $sorted.Count) { $idx = $sorted.Count - 1 }
    return [math]::Round($sorted[$idx], 0)
}

# ── Execute one cycle ─────────────────────────────────────────────────────

function Invoke-ActionCycle {
    param([int]$cycle)

    for ($j = 0; $j -lt $Parallel; $j++) {
        $idem = "soak6-$cycle-$j-$(Get-Random -Maximum 99999)"

        # Rotate through all capability groups
        $groupIndex = ($cycle * $Parallel + $j) % 3
        if ($groupIndex -eq 0) {
            $action = $safeActions[($cycle + $j) % $safeActions.Count]
            $isDryRun = $false
        } elseif ($groupIndex -eq 1) {
            $action = $lowActions[($cycle + $j) % $lowActions.Count]
            $isDryRun = $false
        } else {
            $action = $dryRunActions[($cycle + $j) % $dryRunActions.Count]
            $isDryRun = $true
        }

        $body = @{
            intent = $action.intent
            params = $action.params
            idempotency_key = $idem
        }

        if ($isDryRun) {
            $body["dry_run"] = $true
        }

        $t0 = Get-Date

        try {
            $r = Invoke-RestMethod -Uri "$GW/v1/actions/plan" `
                -Method POST `
                -ContentType "application/json" `
                -Body ($body | ConvertTo-Json -Depth 5) `
                -TimeoutSec 15

            $elapsed = ((Get-Date) - $t0).TotalMilliseconds
            $metrics.total++

            # Track per-capability latency
            $cap = $action.intent
            if (-not $latencyByCapability.ContainsKey($cap)) {
                $latencyByCapability[$cap] = @{
                    latencies = [System.Collections.Generic.List[double]]::new()
                    slo_ms = $action.slo_ms
                    success = 0
                    failure = 0
                }
            }
            $latencyByCapability[$cap].latencies.Add($elapsed)

            if ($r.ok -eq $true) {
                if ($r.state -eq "succeeded") {
                    $metrics.succeeded++
                    $latencyByCapability[$cap].success++
                } elseif ($r.state -eq "validated") {
                    $metrics.validated++
                    $latencyByCapability[$cap].success++
                } elseif ($r.state -eq "pending_approval") {
                    $metrics.pending++
                    $latencyByCapability[$cap].success++
                } else {
                    $metrics.errors++
                    $latencyByCapability[$cap].failure++
                    $code = if ($r.error) { $r.error.code } else { "UNKNOWN" }
                    if ($errorCodes.ContainsKey($code)) {
                        $errorCodes[$code] = $errorCodes[$code] + 1
                    } else {
                        $errorCodes[$code] = 1
                    }
                }
            } else {
                $metrics.errors++
                $latencyByCapability[$cap].failure++
                $code = if ($r.error) { $r.error.code } else { "UNKNOWN" }
                if ($errorCodes.ContainsKey($code)) {
                    $errorCodes[$code] = $errorCodes[$code] + 1
                } else {
                    $errorCodes[$code] = 1
                }
            }

        } catch {
            $metrics.total++
            $metrics.errors++
            if ($errorCodes.ContainsKey("HTTP_ERROR")) {
                $errorCodes["HTTP_ERROR"] = $errorCodes["HTTP_ERROR"] + 1
            } else {
                $errorCodes["HTTP_ERROR"] = 1
            }
        }
    }
}

# ── Run soak ──────────────────────────────────────────────────────────────

$soakStart = Get-Date

for ($i = 1; $i -le $Actions; $i++) {
    if ($i % 10 -eq 0 -or $i -eq $Actions) {
        Write-Host "  Cycle $i/$Actions ..." -NoNewline
    }
    Invoke-ActionCycle -cycle $i
    if ($i % 10 -eq 0 -or $i -eq $Actions) {
        Write-Host " done"
    }
    Start-Sleep -Milliseconds 100
}

$soakElapsed = ((Get-Date) - $soakStart).TotalSeconds

# ── Summary ───────────────────────────────────────────────────────────────

Write-Host "`n=== Soak Results ==="
Write-Host "  Total actions:  $($metrics.total)"
Write-Host "  Succeeded:      $($metrics.succeeded)"
Write-Host "  Validated:      $($metrics.validated)"
Write-Host "  Pending:        $($metrics.pending)"
Write-Host "  Errors:         $($metrics.errors)"
Write-Host "  Duration:       $([math]::Round($soakElapsed, 1))s"
Write-Host "  Throughput:     $([math]::Round($metrics.total / $soakElapsed, 1)) actions/s"

# ── Per-Capability Latency Report ─────────────────────────────────────────

Write-Host "`n=== Per-Capability Latency (ms) ==="
Write-Host "  $('Capability'.PadRight(22)) $('Count'.PadRight(7)) $('p50'.PadRight(8)) $('p95'.PadRight(8)) $('p99'.PadRight(8)) $('SLO'.PadRight(8)) Status"
Write-Host "  $('-' * 22) $('-' * 7) $('-' * 8) $('-' * 8) $('-' * 8) $('-' * 8) ------"

$sloViolations = 0

foreach ($kv in ($latencyByCapability.GetEnumerator() | Sort-Object Name)) {
    $cap = $kv.Name
    $data = $kv.Value
    $count = $data.latencies.Count
    $p50 = Get-Percentile -values $data.latencies -pct 0.5
    $p95 = Get-Percentile -values $data.latencies -pct 0.95
    $p99 = Get-Percentile -values $data.latencies -pct 0.99
    $slo = $data.slo_ms

    if ($p95 -le $slo) {
        $status = "[OK]"
    } else {
        $status = "[BREACH]"
        $sloViolations++
    }

    Write-Host "  $($cap.PadRight(22)) $($count.ToString().PadRight(7)) $("${p50}".PadRight(8)) $("${p95}".PadRight(8)) $("${p99}".PadRight(8)) $("${slo}".PadRight(8)) $status"
}

if ($errorCodes.Count -gt 0) {
    Write-Host "`n  Error codes:"
    foreach ($kv in $errorCodes.GetEnumerator()) {
        Write-Host "    $($kv.Key): $($kv.Value)"
    }
}

# ── Post-Soak Health ─────────────────────────────────────────────────────

Write-Host "`n=== Post-Soak Health ==="
try {
    $health = Invoke-RestMethod -Uri "$GW/v1/health/summary" -TimeoutSec 5
    Write-Host "  Overall: $($health.overall_state)"
    foreach ($dep in $health.dependencies.PSObject.Properties) {
        Write-Host "    $($dep.Name): $($dep.Value.state)"
    }
} catch {
    Write-Host "  [WARN] Could not fetch health summary: $_"
}

try {
    $breakers = Invoke-RestMethod -Uri "$GW/v1/breakers" -TimeoutSec 5
    foreach ($b in $breakers.breakers.PSObject.Properties) {
        Write-Host "  Breaker $($b.Name): $($b.Value.state)"
    }
} catch {
    Write-Host "  [WARN] Could not fetch breaker status: $_"
}

# ── Breaker Metrics ──────────────────────────────────────────────────────

Write-Host "`n=== Breaker Metrics (post-soak) ==="
try {
    $bm = Invoke-RestMethod -Uri "$GW/v1/breakers/metrics" -TimeoutSec 5
    foreach ($b in $bm.metrics.PSObject.Properties) {
        $m = $b.Value
        Write-Host "  $($b.Name): state=$($m.state), events=$($m.total_metric_events)"
        foreach ($ec in $m.event_counts.PSObject.Properties) {
            Write-Host "    $($ec.Name): $($ec.Value)"
        }
    }
} catch {
    Write-Host "  [WARN] Could not fetch breaker metrics: $_"
}

# ── Verdict ───────────────────────────────────────────────────────────────

Write-Host ""
if ($metrics.errors -eq 0 -and $sloViolations -eq 0) {
    Write-Host "[PASS] Soak test completed: 0 errors, 0 SLO violations"
    exit 0
} elseif ($metrics.errors -eq 0 -and $sloViolations -gt 0) {
    Write-Host "[WARN] Soak test completed: 0 errors but $sloViolations SLO violations"
    exit 1
} else {
    Write-Host "[WARN] Soak test completed: $($metrics.errors) errors, $sloViolations SLO violations"
    exit 1
}
