<#
.SYNOPSIS
    Sonia Stage 2 smoke test — verifies all services are healthy and the
    /v1/turn end-to-end pipeline works.

.DESCRIPTION
    1. Checks /healthz on all 6 core services (7000-7050).
    2. Calls POST /v1/turn with a sample payload.
    3. Prints compact PASS/FAIL for every check.
    4. Exits with code 0 on full pass, 1 on any failure.

.NOTES
    Does NOT require "python" on PATH — uses Invoke-RestMethod only.
#>

$ErrorActionPreference = "Stop"

# ── Service definitions ──────────────────────────────────────────────────────
$services = @(
    @{ Name = "api-gateway";    Port = 7000 },
    @{ Name = "model-router";   Port = 7010 },
    @{ Name = "memory-engine";  Port = 7020 },
    @{ Name = "pipecat";        Port = 7030 },
    @{ Name = "openclaw";       Port = 7040 },
    @{ Name = "eva-os";         Port = 7050 }
)

$failures = 0

function Write-Check {
    param([string]$Label, [bool]$Pass, [string]$Detail = "")
    if ($Pass) {
        Write-Host "  [PASS] $Label" -ForegroundColor Green
    } else {
        Write-Host "  [FAIL] $Label  $Detail" -ForegroundColor Red
        $script:failures++
    }
}

# ── 1. Health checks ────────────────────────────────────────────────────────
Write-Host ""
Write-Host "=== Sonia Smoke Test ===" -ForegroundColor Cyan
Write-Host ""
Write-Host "--- Health Checks ---"

foreach ($svc in $services) {
    $url = "http://127.0.0.1:$($svc.Port)/healthz"
    try {
        $resp = Invoke-RestMethod -Uri $url -Method Get -TimeoutSec 5
        $isOk = ($resp.ok -eq $true)
        Write-Check "$($svc.Name) :$($svc.Port)/healthz" $isOk
    } catch {
        Write-Check "$($svc.Name) :$($svc.Port)/healthz" $false $_.Exception.Message
    }
}

# ── 2. Turn endpoint ────────────────────────────────────────────────────────
Write-Host ""
Write-Host "--- Turn Pipeline ---"

$turnBody = @{
    user_id         = "smoke-test"
    conversation_id = "smoke-conv-001"
    input_text      = "What is 2 plus 2?"
    profile         = "chat_low_latency"
} | ConvertTo-Json -Compress

try {
    $turnResp = Invoke-RestMethod `
        -Uri "http://127.0.0.1:7000/v1/turn" `
        -Method Post `
        -ContentType "application/json" `
        -Body $turnBody `
        -TimeoutSec 120

    $turnOk = ($turnResp.ok -eq $true)
    Write-Check "POST /v1/turn -> ok" $turnOk

    $hasText = ($turnResp.assistant_text.Length -gt 0)
    Write-Check "assistant_text non-empty" $hasText

    $hasTurnId = ($turnResp.turn_id -like "turn_*")
    Write-Check "turn_id present" $hasTurnId

    $memWritten = ($turnResp.memory.written -eq $true)
    Write-Check "memory written" $memWritten

    Write-Host ""
    Write-Host "  turn_id        : $($turnResp.turn_id)"
    Write-Host "  assistant_text : $($turnResp.assistant_text.Substring(0, [Math]::Min(120, $turnResp.assistant_text.Length)))..."
    Write-Host "  duration_ms    : $([Math]::Round($turnResp.duration_ms, 1))"
    Write-Host "  memory.retrieved: $($turnResp.memory.retrieved_count)"
    Write-Host "  memory.written : $($turnResp.memory.written)"

} catch {
    Write-Check "POST /v1/turn" $false $_.Exception.Message
}

# ── 3. Second call — verify memory retrieval ────────────────────────────────
Write-Host ""
Write-Host "--- Memory Retrieval (second call) ---"

$turnBody2 = @{
    user_id         = "smoke-test"
    conversation_id = "smoke-conv-001"
    input_text      = "2 plus 2"
    profile         = "chat_low_latency"
} | ConvertTo-Json -Compress

try {
    $turnResp2 = Invoke-RestMethod `
        -Uri "http://127.0.0.1:7000/v1/turn" `
        -Method Post `
        -ContentType "application/json" `
        -Body $turnBody2 `
        -TimeoutSec 120

    $r2Ok = ($turnResp2.ok -eq $true)
    Write-Check "second turn ok" $r2Ok

    $retrieved = $turnResp2.memory.retrieved_count
    $hasMemory = ($retrieved -ge 1)
    Write-Check "retrieved_count >= 1 (got $retrieved)" $hasMemory

} catch {
    Write-Check "second turn" $false $_.Exception.Message
}

# ── Summary ──────────────────────────────────────────────────────────────────
Write-Host ""
if ($failures -eq 0) {
    Write-Host "=== ALL CHECKS PASSED ===" -ForegroundColor Green
    exit 0
} else {
    Write-Host "=== $failures CHECK(S) FAILED ===" -ForegroundColor Red
    exit 1
}
