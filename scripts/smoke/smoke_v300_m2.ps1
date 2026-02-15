<#
.SYNOPSIS
    Smoke test for SONIA v3.0.0 M2 (Identity + Persistence)

.DESCRIPTION
    Verifies:
    1. User CRUD via memory-engine API
    2. API key auth flow (create user, use key)
    3. Session persistence (persist + load)
    4. Conversation history (write + read)

.PARAMETER MemoryUrl
    Memory engine base URL (default: http://127.0.0.1:7020)

.PARAMETER GatewayUrl
    API Gateway base URL (default: http://127.0.0.1:7000)

.PARAMETER SkipServices
    Skip live service checks
#>
param(
    [string]$MemoryUrl = "http://127.0.0.1:7020",
    [string]$GatewayUrl = "http://127.0.0.1:7000",
    [switch]$SkipServices
)

$ErrorActionPreference = "Stop"
$pass = 0
$fail = 0
$skip = 0
$total = 0

function Test-Check {
    param([string]$Name, [scriptblock]$Test)
    $script:total++
    try {
        $result = & $Test
        if ($result) {
            $script:pass++
            Write-Host "  PASS: $Name" -ForegroundColor Green
        } else {
            $script:fail++
            Write-Host "  FAIL: $Name" -ForegroundColor Red
        }
    } catch {
        $script:fail++
        Write-Host "  FAIL: $Name -- $($_.Exception.Message)" -ForegroundColor Red
    }
}

function Test-Skip {
    param([string]$Name)
    $script:total++
    $script:skip++
    Write-Host "  SKIP: $Name" -ForegroundColor Yellow
}

Write-Host "========================================" -ForegroundColor Cyan
Write-Host " SONIA v3.0.0 M2 Smoke Test" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

if ($SkipServices) {
    Test-Skip "Create user"
    Test-Skip "Get user"
    Test-Skip "Look up by key hash"
    Test-Skip "Persist session"
    Test-Skip "Load session"
    Test-Skip "Write turn history"
    Test-Skip "Read turn history"
} else {
    # ---- User CRUD ----
    Write-Host "[User CRUD]" -ForegroundColor White

    $userId = ""
    $apiKey = ""

    Test-Check "Create user" {
        $body = @{ display_name = "Smoke Test User" } | ConvertTo-Json
        $resp = Invoke-RestMethod -Uri "$MemoryUrl/v1/users" -Method POST -Body $body -ContentType "application/json" -TimeoutSec 5
        $script:userId = $resp.user_id
        $script:apiKey = $resp.api_key
        $resp.user_id -match "^usr_" -and $resp.api_key -match "^sk-sonia-"
    }

    Test-Check "Get user" {
        $resp = Invoke-RestMethod -Uri "$MemoryUrl/v1/users/$userId" -TimeoutSec 5
        $resp.display_name -eq "Smoke Test User" -and $resp.status -eq "active"
    }

    Test-Check "Look up by key hash" {
        $python = "S:\envs\sonia-core\python.exe"
        $hash = & $python -W ignore -c "import hashlib; print(hashlib.sha256('$apiKey'.encode()).hexdigest())" 2>$null
        $resp = Invoke-RestMethod -Uri "$MemoryUrl/v1/users/by-key?api_key_hash=$hash" -TimeoutSec 5
        $resp.user_id -eq $userId
    }

    # ---- Session Persistence ----
    Write-Host ""
    Write-Host "[Session Persistence]" -ForegroundColor White

    Test-Check "Persist session" {
        $body = @{
            session_id = "ses_smoke_m2"
            user_id = $userId
            conversation_id = "conv_smoke_m2"
            profile = "chat_low_latency"
            status = "active"
            created_at = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
            expires_at = (Get-Date).AddMinutes(30).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
            last_activity = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
            turn_count = 0
        } | ConvertTo-Json
        $resp = Invoke-RestMethod -Uri "$MemoryUrl/v1/sessions/persist" -Method POST -Body $body -ContentType "application/json" -TimeoutSec 5
        $resp.status -eq "persisted"
    }

    Test-Check "Load session" {
        $resp = Invoke-RestMethod -Uri "$MemoryUrl/v1/sessions/load/ses_smoke_m2" -TimeoutSec 5
        $resp.session_id -eq "ses_smoke_m2" -and $resp.user_id -eq $userId
    }

    # ---- Conversation History ----
    Write-Host ""
    Write-Host "[Conversation History]" -ForegroundColor White

    Test-Check "Write turn history" {
        $body = @{
            turn_id = "turn_smoke_m2"
            session_id = "ses_smoke_m2"
            user_id = $userId
            sequence_num = 1
            user_input = "Hello from smoke test"
            assistant_response = "Hello! This is the smoke test response."
            model_used = "mock"
            latency_ms = 100.0
        } | ConvertTo-Json
        $resp = Invoke-RestMethod -Uri "$MemoryUrl/v1/history/turns" -Method POST -Body $body -ContentType "application/json" -TimeoutSec 5
        $resp.status -eq "stored"
    }

    Test-Check "Read turn history" {
        $resp = Invoke-RestMethod -Uri "$MemoryUrl/v1/sessions/ses_smoke_m2/history" -TimeoutSec 5
        $resp.count -ge 1 -and $resp.turns[0].turn_id -eq "turn_smoke_m2"
    }

    # ---- Cleanup ----
    try {
        Invoke-RestMethod -Uri "$MemoryUrl/v1/users/$userId" -Method DELETE -TimeoutSec 5 | Out-Null
    } catch {}
}

# ---- Summary ----
Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host " Results: $pass passed, $fail failed, $skip skipped / $total total" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

if ($fail -gt 0) {
    Write-Host " SMOKE TEST FAILED" -ForegroundColor Red
    exit 1
} else {
    Write-Host " SMOKE TEST PASSED" -ForegroundColor Green
    exit 0
}
