<#
.SYNOPSIS
    Smoke test for SONIA v3.0.0 M1 (Contract + Config Cut)

.DESCRIPTION
    Verifies:
    1. Config validates against schema
    2. All 8 services /healthz return contract_version = "v3.0.0"
    3. /v3/turn endpoint exists and accepts requests
    4. /v1/turn returns X-Deprecated header
    5. /v3/chat endpoint exists

.PARAMETER GatewayUrl
    API Gateway base URL (default: http://127.0.0.1:7000)

.PARAMETER SkipServices
    Skip service health checks (useful when services aren't running)
#>
param(
    [string]$GatewayUrl = "http://127.0.0.1:7000",
    [switch]$SkipServices
)

$ErrorActionPreference = "Stop"
$python = "S:\envs\sonia-core\python.exe"
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
Write-Host " SONIA v3.0.0 M1 Smoke Test" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# ── Config validation ────────────────────────────────────────────────────
Write-Host "[Config Schema]" -ForegroundColor White

Test-Check "Config schema validates" {
    $validateScript = @"
import sys
sys.path.insert(0, r'S:\services\shared')
from config_validator import SoniaConfig
cfg = SoniaConfig()
assert cfg.version == '3.0.0', f'version={cfg.version}'
assert cfg.schema_version == '3.0.0', f'schema={cfg.schema_version}'
print('OK')
"@
    $out = & $python -W ignore -c $validateScript 2>&1
    $out -match "OK"
}

Test-Check "version.py exports SONIA_CONTRACT" {
    $out = & $python -W ignore -c "import sys; sys.path.insert(0,r'S:\services\shared'); from version import SONIA_CONTRACT; print(SONIA_CONTRACT)" 2>&1
    $out -match "v3.0.0"
}

# ── Service health checks ───────────────────────────────────────────────
Write-Host ""
Write-Host "[Service Health Checks]" -ForegroundColor White

$services = @(
    @{ Name = "api-gateway";     Port = 7000 },
    @{ Name = "model-router";    Port = 7010 },
    @{ Name = "memory-engine";   Port = 7020 },
    @{ Name = "pipecat";         Port = 7030 },
    @{ Name = "openclaw";        Port = 7040 },
    @{ Name = "eva-os";          Port = 7050 },
    @{ Name = "vision-capture";  Port = 7060 },
    @{ Name = "perception";      Port = 7070 }
)

if ($SkipServices) {
    foreach ($svc in $services) {
        Test-Skip "$($svc.Name) healthz contract_version"
    }
} else {
    foreach ($svc in $services) {
        Test-Check "$($svc.Name) healthz contract_version" {
            $url = "http://127.0.0.1:$($svc.Port)/healthz"
            try {
                $resp = Invoke-RestMethod -Uri $url -TimeoutSec 5
                $resp.contract_version -eq "v3.0.0"
            } catch {
                $false
            }
        }
    }
}

# ── V3 endpoint checks ──────────────────────────────────────────────────
Write-Host ""
Write-Host "[V3 Endpoint Checks]" -ForegroundColor White

if ($SkipServices) {
    Test-Skip "GET /v3/capabilities"
    Test-Skip "POST /v3/turn returns contract_version"
    Test-Skip "POST /v1/turn returns X-Deprecated header"
    Test-Skip "POST /v3/chat returns contract_version"
} else {
    Test-Check "GET /v3/capabilities" {
        try {
            $resp = Invoke-RestMethod -Uri "$GatewayUrl/v3/capabilities" -TimeoutSec 5
            $resp.contract_version -eq "v3.0.0"
        } catch {
            $false
        }
    }

    Test-Check "POST /v3/turn returns contract_version" {
        try {
            $body = @{ user_input = "hello"; session_id = "smoke-test" } | ConvertTo-Json
            $resp = Invoke-RestMethod -Uri "$GatewayUrl/v3/turn" -Method POST -Body $body -ContentType "application/json" -TimeoutSec 10
            $resp.contract_version -eq "v3.0.0"
        } catch {
            # 502/503 from downstream is OK -- we just check the gateway responds
            $false
        }
    }

    Test-Check "POST /v1/turn returns X-Deprecated header" {
        try {
            $body = @{ user_input = "hello"; session_id = "smoke-test" } | ConvertTo-Json
            $webResp = Invoke-WebRequest -Uri "$GatewayUrl/v1/turn" -Method POST -Body $body -ContentType "application/json" -TimeoutSec 10
            $webResp.Headers["X-Deprecated"] -eq "true"
        } catch {
            if ($_.Exception.Response) {
                $headers = $_.Exception.Response.Headers
                $dep = $null
                try { $dep = $headers.GetValues("X-Deprecated") } catch {}
                if ($dep) { $dep[0] -eq "true" } else { $false }
            } else {
                $false
            }
        }
    }

    Test-Check "POST /v3/chat returns contract_version" {
        try {
            $body = @{ message = "hello"; session_id = "smoke-test" } | ConvertTo-Json
            $resp = Invoke-RestMethod -Uri "$GatewayUrl/v3/chat" -Method POST -Body $body -ContentType "application/json" -TimeoutSec 10
            $resp.contract_version -eq "v3.0.0"
        } catch {
            $false
        }
    }
}

# ── Summary ──────────────────────────────────────────────────────────────
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
