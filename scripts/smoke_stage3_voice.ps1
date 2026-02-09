<#
.SYNOPSIS
    Stage 3 smoke test — session lifecycle, WebSocket stream (text fallback),
    and confirmation queue.

.NOTES
    Uses Invoke-RestMethod for HTTP.
    Uses the sonia-core env Python for WebSocket tests.
    Exits 0 on full pass, 1 on any failure.
#>

$ErrorActionPreference = "Stop"
$Python = "S:\envs\sonia-core\python.exe"

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

Write-Host ""
Write-Host "=== Stage 3 Smoke Test ===" -ForegroundColor Cyan

# ── 1. Health checks ────────────────────────────────────────────────────────
Write-Host ""
Write-Host "--- Health Checks ---"
foreach ($svc in $services) {
    $url = "http://127.0.0.1:$($svc.Port)/healthz"
    try {
        $resp = Invoke-RestMethod -Uri $url -Method Get -TimeoutSec 5
        Write-Check "$($svc.Name) :$($svc.Port)/healthz" ($resp.ok -eq $true)
    } catch {
        Write-Check "$($svc.Name) :$($svc.Port)/healthz" $false $_.Exception.Message
    }
}

# ── 2. Session create / get / delete ────────────────────────────────────────
Write-Host ""
Write-Host "--- Session Lifecycle ---"

$sessBody = @{
    user_id         = "smoke3-user"
    conversation_id = "smoke3-conv"
    profile         = "chat_low_latency"
} | ConvertTo-Json -Compress

$sessId = ""
try {
    $cr = Invoke-RestMethod -Uri "http://127.0.0.1:7000/v1/sessions" -Method Post -ContentType "application/json" -Body $sessBody -TimeoutSec 10
    $sessId = $cr.session_id
    Write-Check "POST /v1/sessions -> ok" ($cr.ok -eq $true)
    Write-Check "session_id present" ($sessId -like "ses_*")
} catch {
    Write-Check "POST /v1/sessions" $false $_.Exception.Message
}

if ($sessId) {
    try {
        $gr = Invoke-RestMethod -Uri "http://127.0.0.1:7000/v1/sessions/$sessId" -Method Get -TimeoutSec 5
        Write-Check "GET session -> active" ($gr.status -eq "active")
    } catch {
        Write-Check "GET session" $false $_.Exception.Message
    }
}

# ── 3. WebSocket text fallback turn ─────────────────────────────────────────
Write-Host ""
Write-Host "--- Stream Text Fallback ---"

if ($sessId) {
    # Write a small Python script to test the WebSocket
    $wsTmpFile = "$env:TEMP\smoke3_ws_test.py"
    $wsCode = @'
import asyncio, json, sys

async def main():
    from websockets.client import connect
    sid = sys.argv[1]
    try:
        async with connect(f"ws://127.0.0.1:7000/v1/stream/{sid}") as ws:
            ack = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
            if ack.get("type") != "ack":
                print("FAIL:no_ack")
                return
            await ws.send(json.dumps({"type": "input.text", "payload": {"text": "What is 3 plus 3?"}}))
            for _ in range(10):
                ev = json.loads(await asyncio.wait_for(ws.recv(), timeout=120))
                if ev.get("type") == "response.final":
                    text = ev.get("payload", {}).get("assistant_text", "")
                    if text:
                        print("PASS:" + text[:80])
                    else:
                        print("FAIL:empty_text")
                    return
            print("FAIL:no_final")
    except Exception as e:
        print(f"FAIL:{e}")

asyncio.run(main())
'@
    Set-Content -Path $wsTmpFile -Value $wsCode -Encoding UTF8
    $wsResultRaw = & $Python -W ignore $wsTmpFile $sessId 2>&1
    $wsResult = ($wsResultRaw | Where-Object { $_ -is [string] -or $_ -is [System.Management.Automation.PSObject] }) -join "`n"
    $wsResult = $wsResult.Trim()
    # Extract last PASS/FAIL line
    $wsLines = $wsResult -split "`n" | Where-Object { $_.StartsWith("PASS:") -or $_.StartsWith("FAIL:") }
    if ($wsLines) {
        $wsResult = ($wsLines | Select-Object -Last 1).Trim()
    }
    $wsPass = $wsResult.StartsWith("PASS:")
    Write-Check "WS input.text -> response.final" $wsPass $wsResult
    Remove-Item $wsTmpFile -Force -ErrorAction SilentlyContinue
} else {
    Write-Check "WS test skipped (no session)" $false
}

# ── 4. Confirmation queue ───────────────────────────────────────────────────
Write-Host ""
Write-Host "--- Confirmation Queue ---"

if ($sessId) {
    try {
        $pend = Invoke-RestMethod -Uri "http://127.0.0.1:7000/v1/confirmations/pending?session_id=$sessId" -Method Get -TimeoutSec 5
        Write-Check "GET pending -> ok" ($pend.ok -eq $true)
        Write-Check "pending count is int" ($pend.count -ge 0)
    } catch {
        Write-Check "GET pending" $false $_.Exception.Message
    }
}

# ── 5. Session delete ──────────────────────────────────────────────────────
Write-Host ""
Write-Host "--- Session Cleanup ---"

if ($sessId) {
    try {
        $dr = Invoke-RestMethod -Uri "http://127.0.0.1:7000/v1/sessions/$sessId" -Method Delete -TimeoutSec 5
        Write-Check "DELETE session -> ok" ($dr.ok -eq $true)
    } catch {
        Write-Check "DELETE session" $false $_.Exception.Message
    }
}

# ── 6. Stage 2 regression ──────────────────────────────────────────────────
Write-Host ""
Write-Host "--- Stage 2 Regression ---"

$turnBody = @{
    user_id = "smoke3-s2"
    conversation_id = "smoke3-s2-conv"
    input_text = "What is 2 plus 2?"
    profile = "chat_low_latency"
} | ConvertTo-Json -Compress

try {
    $tr = Invoke-RestMethod -Uri "http://127.0.0.1:7000/v1/turn" -Method Post -ContentType "application/json" -Body $turnBody -TimeoutSec 120
    Write-Check "POST /v1/turn -> ok" ($tr.ok -eq $true)
    Write-Check "assistant_text non-empty" ($tr.assistant_text.Length -gt 0)
    Write-Check "turn_id present" ($tr.turn_id -like "turn_*")
} catch {
    Write-Check "POST /v1/turn" $false $_.Exception.Message
}

# ── Summary ──────────────────────────────────────────────────────────────────
Write-Host ""
if ($failures -eq 0) {
    Write-Host "=== ALL STAGE 3 CHECKS PASSED ===" -ForegroundColor Green
    exit 0
} else {
    Write-Host "=== $failures CHECK(S) FAILED ===" -ForegroundColor Red
    exit 1
}
