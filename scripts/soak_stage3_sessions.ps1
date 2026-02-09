<#
.SYNOPSIS
    Stage 3 soak test — sequential turns across multiple sessions.
    Prints latency summary and error count.

.PARAMETER Sessions
    Number of sessions to create (default: 3)

.PARAMETER TurnsPerSession
    Turns per session (default: 2)
#>

param(
    [int]$Sessions = 3,
    [int]$TurnsPerSession = 2
)

$ErrorActionPreference = "Stop"
$GW = "http://127.0.0.1:7000"

$totalTurns = 0
$totalErrors = 0
$latencies = @()

Write-Host ""
Write-Host "=== Stage 3 Soak Test ===" -ForegroundColor Cyan
Write-Host "  Sessions: $Sessions, Turns/session: $TurnsPerSession"
Write-Host ""

for ($s = 1; $s -le $Sessions; $s++) {
    # Create session
    $sessBody = @{
        user_id         = "soak-user-$s"
        conversation_id = "soak-conv-$s"
    } | ConvertTo-Json -Compress

    try {
        $cr = Invoke-RestMethod -Uri "$GW/v1/sessions" -Method Post -ContentType "application/json" -Body $sessBody -TimeoutSec 10
        $sid = $cr.session_id
        Write-Host "Session ${s}/${Sessions} created: $sid" -ForegroundColor Gray
    } catch {
        Write-Host "  [ERROR] Session create failed: $_" -ForegroundColor Red
        $totalErrors++
        continue
    }

    for ($t = 1; $t -le $TurnsPerSession; $t++) {
        $turnBody = @{
            user_id         = "soak-user-$s"
            conversation_id = "soak-conv-$s"
            input_text      = "Turn $t of session $s. What is $($s * 10 + $t) plus 1?"
            profile         = "chat_low_latency"
        } | ConvertTo-Json -Compress

        try {
            $tr = Invoke-RestMethod -Uri "$GW/v1/turn" -Method Post -ContentType "application/json" -Body $turnBody -TimeoutSec 120
            $totalTurns++
            if ($tr.ok -eq $true) {
                $lat = [math]::Round($tr.duration_ms, 0)
                $latencies += $lat
                Write-Host "  Turn ${t}/${TurnsPerSession}: ${lat}ms  text=$($tr.assistant_text.Substring(0, [Math]::Min(60, $tr.assistant_text.Length)))..." -ForegroundColor Gray
            } else {
                $totalErrors++
                Write-Host "  Turn ${t}/${TurnsPerSession}: FAILED ($($tr.error.message))" -ForegroundColor Red
            }
        } catch {
            $totalErrors++
            Write-Host "  Turn ${t}/${TurnsPerSession}: ERROR ($_)" -ForegroundColor Red
        }
    }

    # Close session
    try {
        Invoke-RestMethod -Uri "$GW/v1/sessions/$sid" -Method Delete -TimeoutSec 5 | Out-Null
    } catch {}
}

# ── Summary ──────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "=== Soak Summary ===" -ForegroundColor Cyan

if ($latencies.Count -gt 0) {
    $sorted = $latencies | Sort-Object
    $avg = [math]::Round(($latencies | Measure-Object -Average).Average, 0)
    $p50 = $sorted[[math]::Floor($sorted.Count * 0.5)]
    $p95 = $sorted[[math]::Floor($sorted.Count * 0.95)]
    $min = $sorted[0]
    $max = $sorted[-1]
    Write-Host "  Total turns : $totalTurns"
    Write-Host "  Errors      : $totalErrors"
    Write-Host "  Avg latency : ${avg}ms"
    Write-Host "  P50 latency : ${p50}ms"
    Write-Host "  P95 latency : ${p95}ms"
    Write-Host "  Min/Max     : ${min}ms / ${max}ms"
} else {
    Write-Host "  No successful turns."
}

if ($totalErrors -gt 0) {
    Write-Host ""
    Write-Host "=== $totalErrors ERROR(S) ===" -ForegroundColor Red
    exit 1
} else {
    Write-Host ""
    Write-Host "=== SOAK PASSED ===" -ForegroundColor Green
    exit 0
}
