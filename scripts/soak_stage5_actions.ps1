<#
.SYNOPSIS
    Stage 5 soak test — exercises the full action pipeline under sustained load.
.PARAMETER Actions
    Number of action cycles to run (default 10).
.PARAMETER Parallel
    Number of concurrent actions per cycle (default 3).
#>
param(
    [int]$Actions = 10,
    [int]$Parallel = 3
)

$ErrorActionPreference = "Stop"
$GW = "http://127.0.0.1:7000"

# ── Preflight ──────────────────────────────────────────────────────────────

Write-Host "`n=== Stage 5 Soak Test ==="
Write-Host "Actions: $Actions, Parallel: $Parallel"

try {
    $h = Invoke-RestMethod -Uri "$GW/healthz" -TimeoutSec 5
    if (-not $h.ok) { throw "Gateway not healthy" }
    Write-Host "[OK] Gateway healthy"
} catch {
    Write-Host "[FAIL] Gateway health check failed: $_"
    exit 1
}

# ── Test Data ──────────────────────────────────────────────────────────────

$safeActions = @(
    @{ intent = "file.read"; params = @{ path = "S:\config\sonia-config.json" } },
    @{ intent = "window.list"; params = @{} },
    @{ intent = "clipboard.read"; params = @{} }
)

$guardedActions = @(
    @{ intent = "shell.run"; params = @{ command = "Get-ChildItem" } },
    @{ intent = "app.launch"; params = @{ target = "notepad.exe" } },
    @{ intent = "keyboard.type"; params = @{ text = "soak test" } }
)

# ── Metrics ────────────────────────────────────────────────────────────────

$metrics = @{
    total = 0
    succeeded = 0
    pending = 0
    denied = 0
    errors = 0
    latencies = [System.Collections.Generic.List[double]]::new()
}

$errorCodes = @{}

# ── Execute one cycle ─────────────────────────────────────────────────────

function Invoke-ActionCycle {
    param([int]$cycle)

    # Mix safe and guarded actions
    for ($j = 0; $j -lt $Parallel; $j++) {
        $idem = "soak-$cycle-$j-$(Get-Random -Maximum 99999)"

        if ($j % 2 -eq 0) {
            # Safe action
            $action = $safeActions[$j % $safeActions.Count]
        } else {
            # Guarded action (dry_run to avoid side effects)
            $action = $guardedActions[$j % $guardedActions.Count]
        }

        $body = @{
            intent = $action.intent
            params = $action.params
            idempotency_key = $idem
        }

        # Use dry_run for guarded actions in soak
        if ($j % 2 -ne 0) {
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
            $metrics.latencies.Add($elapsed)

            if ($r.ok -eq $true) {
                if ($r.state -eq "succeeded") {
                    $metrics.succeeded++
                } elseif ($r.state -eq "validated") {
                    $metrics.succeeded++  # dry_run counts as success
                } elseif ($r.state -eq "pending_approval") {
                    $metrics.pending++
                } else {
                    $metrics.errors++
                    $code = if ($r.error) { $r.error.code } else { "UNKNOWN" }
                    if ($errorCodes.ContainsKey($code)) {
                        $errorCodes[$code] = $errorCodes[$code] + 1
                    } else {
                        $errorCodes[$code] = 1
                    }
                }
            } else {
                $metrics.errors++
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
    Write-Host "  Cycle $i/$Actions ..." -NoNewline
    Invoke-ActionCycle -cycle $i
    Write-Host " done"
    Start-Sleep -Milliseconds 200
}

$soakElapsed = ((Get-Date) - $soakStart).TotalSeconds

# ── Summary ───────────────────────────────────────────────────────────────

Write-Host "`n=== Soak Results ==="
Write-Host "  Total actions:  $($metrics.total)"
Write-Host "  Succeeded:      $($metrics.succeeded)"
Write-Host "  Pending:        $($metrics.pending)"
Write-Host "  Errors:         $($metrics.errors)"
Write-Host "  Duration:       $([math]::Round($soakElapsed, 1))s"

if ($metrics.latencies.Count -gt 0) {
    $sorted = $metrics.latencies | Sort-Object
    $p50idx = [math]::Floor($sorted.Count * 0.5)
    $p95idx = [math]::Floor($sorted.Count * 0.95)
    if ($p95idx -ge $sorted.Count) { $p95idx = $sorted.Count - 1 }
    $p50 = [math]::Round($sorted[$p50idx], 0)
    $p95 = [math]::Round($sorted[$p95idx], 0)
    Write-Host "  p50 latency:    ${p50}ms"
    Write-Host "  p95 latency:    ${p95}ms"
}

if ($errorCodes.Count -gt 0) {
    Write-Host "  Error codes:"
    foreach ($kv in $errorCodes.GetEnumerator()) {
        Write-Host "    $($kv.Key): $($kv.Value)"
    }
}

# ── Health after soak ─────────────────────────────────────────────────────

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

# ── Verdict ───────────────────────────────────────────────────────────────

if ($metrics.errors -eq 0) {
    Write-Host "`n[PASS] Soak test completed with 0 errors"
    exit 0
} else {
    Write-Host "`n[WARN] Soak test completed with $($metrics.errors) errors"
    exit 1
}
