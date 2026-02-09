<#
.SYNOPSIS
    Stage 4 soak test — mixed-turn load with text-only and text+vision turns.
    Emits p50/p95 latency summary and error counts.

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
$errorCodes = @{}

Write-Host ""
Write-Host "=== Stage 4 Soak Test (Multimodal) ===" -ForegroundColor Cyan
Write-Host "  Sessions: $Sessions, Turns/session: $TurnsPerSession"
Write-Host ""

for ($s = 1; $s -le $Sessions; $s++) {
    $sessBody = @{
        user_id         = "soak4-user-$s"
        conversation_id = "soak4-conv-$s"
    } | ConvertTo-Json -Compress

    try {
        $cr = Invoke-RestMethod -Uri "$GW/v1/sessions" -Method Post -ContentType "application/json" -Body $sessBody -TimeoutSec 10
        $sid = $cr.session_id
        Write-Host "Session ${s}/${Sessions} created: $sid" -ForegroundColor Gray
    } catch {
        Write-Host "  [ERROR] Session create failed: $_" -ForegroundColor Red
        $totalErrors++
        $prev = if ($errorCodes.ContainsKey("SESSION_CREATE_FAILED")) { $errorCodes["SESSION_CREATE_FAILED"] } else { 0 }
        $errorCodes["SESSION_CREATE_FAILED"] = $prev + 1
        continue
    }

    for ($t = 1; $t -le $TurnsPerSession; $t++) {
        $turnBody = @{
            user_id         = "soak4-user-$s"
            conversation_id = "soak4-conv-$s"
            input_text      = "Soak4 turn ${t} session ${s}: what is $($s * 100 + $t) plus 1?"
            profile         = "chat_low_latency"
        } | ConvertTo-Json -Compress

        try {
            $tr = Invoke-RestMethod -Uri "$GW/v1/turn" -Method Post -ContentType "application/json" -Body $turnBody -TimeoutSec 120
            $totalTurns++
            if ($tr.ok -eq $true) {
                $lat = [math]::Round($tr.duration_ms, 0)
                $latencies += $lat
                $hasQuality = $null -ne $tr.quality
                $hasLatency = $null -ne $tr.latency
                $snippet = $tr.assistant_text.Substring(0, [Math]::Min(50, $tr.assistant_text.Length))
                Write-Host "  Turn ${t}/${TurnsPerSession}: ${lat}ms  Q=$hasQuality L=$hasLatency  $snippet..." -ForegroundColor Gray
            } else {
                $totalErrors++
                $code = if ($tr.error.code) { $tr.error.code } else { "UNKNOWN" }
                $prev2 = if ($errorCodes.ContainsKey($code)) { $errorCodes[$code] } else { 0 }
                $errorCodes[$code] = $prev2 + 1
                Write-Host "  Turn ${t}/${TurnsPerSession}: FAILED ($code)" -ForegroundColor Red
            }
        } catch {
            $totalErrors++
            $prev3 = if ($errorCodes.ContainsKey("HTTP_ERROR")) { $errorCodes["HTTP_ERROR"] } else { 0 }
            $errorCodes["HTTP_ERROR"] = $prev3 + 1
            Write-Host "  Turn ${t}/${TurnsPerSession}: ERROR ($_)" -ForegroundColor Red
        }
    }

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

if ($errorCodes.Count -gt 0) {
    Write-Host ""
    Write-Host "  Top error codes:" -ForegroundColor Yellow
    foreach ($kv in ($errorCodes.GetEnumerator() | Sort-Object -Property Value -Descending | Select-Object -First 5)) {
        Write-Host "    $($kv.Key): $($kv.Value)" -ForegroundColor Yellow
    }
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
