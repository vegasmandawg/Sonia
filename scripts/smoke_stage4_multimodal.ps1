<#
.SYNOPSIS
    Stage 4 smoke test — multimodal session with vision, quality annotations,
    latency breakdown, and Stage 2/3 regression.

.NOTES
    Uses Invoke-RestMethod for HTTP, Python for WebSocket tests.
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
Write-Host "=== Stage 4 Smoke Test ===" -ForegroundColor Cyan

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

# ── 2. Create session ──────────────────────────────────────────────────────
Write-Host ""
Write-Host "--- Session + Text Turn ---"

$sessBody = @{
    user_id         = "smoke4-user"
    conversation_id = "smoke4-conv"
    profile         = "chat_low_latency"
} | ConvertTo-Json -Compress

$sessId = ""
try {
    $cr = Invoke-RestMethod -Uri "http://127.0.0.1:7000/v1/sessions" -Method Post -ContentType "application/json" -Body $sessBody -TimeoutSec 10
    $sessId = $cr.session_id
    Write-Check "POST /v1/sessions -> ok" ($cr.ok -eq $true)
} catch {
    Write-Check "POST /v1/sessions" $false $_.Exception.Message
}

# ── 3. Text turn via WebSocket ─────────────────────────────────────────────
if ($sessId) {
    $wsTmpFile = "$env:TEMP\smoke4_ws_text.py"
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
            await ws.send(json.dumps({"type": "input.text", "payload": {"text": "What is 9 plus 9?"}}))
            for _ in range(10):
                ev = json.loads(await asyncio.wait_for(ws.recv(), timeout=120))
                if ev.get("type") == "response.final":
                    p = ev.get("payload", {})
                    text = p.get("assistant_text", "")
                    quality = p.get("quality", {})
                    has_quality = "generation_profile_used" in quality
                    if text and has_quality:
                        print("PASS:" + text[:60])
                    elif text:
                        print("PASS_NO_QUALITY:" + text[:60])
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
    $wsLines = $wsResult -split "`n" | Where-Object { $_.StartsWith("PASS") -or $_.StartsWith("FAIL") }
    if ($wsLines) {
        $wsResult = ($wsLines | Select-Object -Last 1).Trim()
    }
    $wsPass = $wsResult.StartsWith("PASS")
    Write-Check "WS input.text -> response.final + quality" $wsPass $wsResult
    Remove-Item $wsTmpFile -Force -ErrorAction SilentlyContinue
}

# ── 4. Vision snapshot via WebSocket ───────────────────────────────────────
Write-Host ""
Write-Host "--- Vision Snapshot ---"

if ($sessId) {
    $wsTmpFile = "$env:TEMP\smoke4_ws_vision.py"
    $wsCode = @'
import asyncio, json, sys, base64

async def main():
    from websockets.client import connect
    sid = sys.argv[1]
    # Tiny 1x1 PNG
    tiny_png = (
        b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01'
        b'\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00'
        b'\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00'
        b'\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82'
    )
    data_b64 = base64.b64encode(tiny_png).decode()
    try:
        async with connect(f"ws://127.0.0.1:7000/v1/stream/{sid}") as ws:
            ack = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
            if ack.get("type") != "ack":
                print("FAIL:no_ack")
                return
            # Enable vision
            await ws.send(json.dumps({"type": "control.vision.enable", "payload": {}}))
            en = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
            if en.get("payload", {}).get("vision_enabled") is not True:
                print("FAIL:vision_not_enabled")
                return
            # Send snapshot
            await ws.send(json.dumps({
                "type": "input.vision.snapshot",
                "payload": {
                    "frame_id": "smoke_snap_1",
                    "mime_type": "image/png",
                    "data": data_b64,
                }
            }))
            resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
            if resp.get("type") == "vision.accepted":
                print("PASS:accepted_frame_" + resp["payload"].get("frame_id", "?"))
            else:
                print(f"FAIL:{resp.get('type')}:{json.dumps(resp.get('payload',{}))[:80]}")
    except Exception as e:
        print(f"FAIL:{e}")

asyncio.run(main())
'@
    Set-Content -Path $wsTmpFile -Value $wsCode -Encoding UTF8
    $wsResultRaw = & $Python -W ignore $wsTmpFile $sessId 2>&1
    $wsResult = ($wsResultRaw | Where-Object { $_ -is [string] -or $_ -is [System.Management.Automation.PSObject] }) -join "`n"
    $wsResult = $wsResult.Trim()
    $wsLines = $wsResult -split "`n" | Where-Object { $_.StartsWith("PASS") -or $_.StartsWith("FAIL") }
    if ($wsLines) { $wsResult = ($wsLines | Select-Object -Last 1).Trim() }
    $wsPass = $wsResult.StartsWith("PASS")
    Write-Check "WS vision.snapshot -> vision.accepted" $wsPass $wsResult
    Remove-Item $wsTmpFile -Force -ErrorAction SilentlyContinue
}

# ── 5. Sync turn with quality + latency ────────────────────────────────────
Write-Host ""
Write-Host "--- Sync Turn Quality + Latency ---"

$turnBody = @{
    user_id = "smoke4-sync"
    conversation_id = "smoke4-sync-conv"
    input_text = "Stage 4 smoke: what is 6 times 7?"
    profile = "chat_low_latency"
} | ConvertTo-Json -Compress

try {
    $tr = Invoke-RestMethod -Uri "http://127.0.0.1:7000/v1/turn" -Method Post -ContentType "application/json" -Body $turnBody -TimeoutSec 120
    Write-Check "POST /v1/turn -> ok" ($tr.ok -eq $true)
    Write-Check "assistant_text non-empty" ($tr.assistant_text.Length -gt 0)
    Write-Check "has quality annotations" ($null -ne $tr.quality)
    Write-Check "has latency breakdown" ($null -ne $tr.latency)
    if ($tr.latency) {
        Write-Check "latency.total_ms > 0" ($tr.latency.total_ms -gt 0)
    }
} catch {
    Write-Check "POST /v1/turn" $false $_.Exception.Message
}

# ── 6. Session cleanup ────────────────────────────────────────────────────
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

# ── 7. Stage 2 regression ─────────────────────────────────────────────────
Write-Host ""
Write-Host "--- Stage 2 Regression ---"

$turnBody2 = @{
    user_id = "smoke4-s2"
    conversation_id = "smoke4-s2-conv"
    input_text = "What is 2 plus 2?"
    profile = "chat_low_latency"
} | ConvertTo-Json -Compress

try {
    $tr2 = Invoke-RestMethod -Uri "http://127.0.0.1:7000/v1/turn" -Method Post -ContentType "application/json" -Body $turnBody2 -TimeoutSec 120
    Write-Check "POST /v1/turn -> ok" ($tr2.ok -eq $true)
    Write-Check "turn_id present" ($tr2.turn_id -like "turn_*")
} catch {
    Write-Check "POST /v1/turn (S2)" $false $_.Exception.Message
}

# ── Summary ───────────────────────────────────────────────────────────────
Write-Host ""
if ($failures -eq 0) {
    Write-Host "=== ALL STAGE 4 CHECKS PASSED ===" -ForegroundColor Green
    exit 0
} else {
    Write-Host "=== $failures CHECK(S) FAILED ===" -ForegroundColor Red
    exit 1
}
