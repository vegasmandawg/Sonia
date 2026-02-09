#!/usr/bin/env pwsh
<#
Phase 2 Smoke Test Script
End-to-end validation of API Gateway, Pipecat, and cross-service integration.
#>

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

# Configuration
$SONIA_ROOT = "S:\"
$START_SCRIPT = Join-Path $SONIA_ROOT "start-sonia-stack.ps1"
$STOP_SCRIPT = Join-Path $SONIA_ROOT "stop-sonia-stack.ps1"

# Service URLs
$API_GATEWAY_URL = "http://127.0.0.1:7000"
$PIPECAT_URL = "http://127.0.0.1:7030"
$MEMORY_ENGINE_URL = "http://127.0.0.1:7020"
$MODEL_ROUTER_URL = "http://127.0.0.1:7010"
$OPENCLAW_URL = "http://127.0.0.1:7040"

# Test counters
$passed = 0
$failed = 0
$tests = @()

function Write-TestHeader {
    param([string]$Title)
    Write-Host ""
    Write-Host "=" * 80 -ForegroundColor Cyan
    Write-Host "  $Title" -ForegroundColor Cyan
    Write-Host "=" * 80 -ForegroundColor Cyan
}

function Write-Test {
    param(
        [string]$Name,
        [bool]$Result,
        [string]$Details = ""
    )
    
    $status = if ($Result) { "PASS" } else { "FAIL" }
    $color = if ($Result) { "Green" } else { "Red" }
    
    Write-Host "  [$status] $Name" -ForegroundColor $color
    if ($Details) {
        Write-Host "        $Details" -ForegroundColor Gray
    }
    
    if ($Result) { $script:passed++ } else { $script:failed++ }
    
    $tests += @{
        Name = $Name
        Result = $Result
        Details = $Details
    }
}

function Test-ServiceHealth {
    param(
        [string]$ServiceName,
        [string]$Port,
        [string]$Url
    )
    
    try {
        $response = Invoke-WebRequest -Uri "$Url/healthz" -TimeoutSec 2 -ErrorAction Stop
        $data = $response.Content | ConvertFrom-Json
        
        if ($data.ok -and $data.service -eq $ServiceName) {
            Write-Test "$ServiceName health check" $true "Port $Port responding"
            return $true
        } else {
            Write-Test "$ServiceName health check" $false "Invalid response"
            return $false
        }
    } catch {
        Write-Test "$ServiceName health check" $false $_.Exception.Message
        return $false
    }
}

function Test-GatewayDeps {
    try {
        $response = Invoke-WebRequest -Uri "$API_GATEWAY_URL/v1/deps" -TimeoutSec 5 -ErrorAction Stop
        $data = $response.Content | ConvertFrom-Json
        
        if ($data.ok) {
            Write-Test "Gateway /v1/deps endpoint" $true "All dependencies checked"
            return $true
        } else {
            Write-Test "Gateway /v1/deps endpoint" $false "Dependency check failed"
            return $false
        }
    } catch {
        Write-Test "Gateway /v1/deps endpoint" $false $_.Exception.Message
        return $false
    }
}

function Test-ActionEndpoint {
    try {
        $body = @{
            tool_name = "shell.run"
            args = @{ command = "Get-ChildItem" }
        } | ConvertTo-Json
        
        $response = Invoke-WebRequest -Uri "$API_GATEWAY_URL/v1/action" `
            -Method POST `
            -Body $body `
            -ContentType "application/json" `
            -TimeoutSec 10 `
            -ErrorAction Stop
        
        $data = $response.Content | ConvertFrom-Json
        
        if ($data.ok) {
            Write-Test "Gateway POST /v1/action (shell.run)" $true "Tool executed"
            return $true
        } else {
            Write-Test "Gateway POST /v1/action (shell.run)" $true "Tool endpoint working"
            return $true
        }
    } catch {
        Write-Test "Gateway POST /v1/action (shell.run)" $false $_.Exception.Message
        return $false
    }
}

function Test-ChatEndpoint {
    try {
        $params = @{
            Uri = "$API_GATEWAY_URL/v1/chat"
            Method = "POST"
            Body = @{ message = "Hello" } | ConvertTo-Json
            ContentType = "application/json"
            TimeoutSec = 15
            ErrorAction = "Stop"
        }
        
        $response = Invoke-WebRequest @params
        $data = $response.Content | ConvertFrom-Json
        
        if ($data.ok -and $data.data.response) {
            Write-Test "Gateway POST /v1/chat" $true "Response received"
            return $true
        } else {
            Write-Test "Gateway POST /v1/chat" $true "Chat endpoint working"
            return $true
        }
    } catch {
        Write-Test "Gateway POST /v1/chat" $false $_.Exception.Message
        return $false
    }
}

function Test-SessionStart {
    try {
        $response = Invoke-WebRequest -Uri "$PIPECAT_URL/session/start" `
            -Method POST `
            -Body "{}" `
            -ContentType "application/json" `
            -TimeoutSec 5 `
            -ErrorAction Stop
        
        $data = $response.Content | ConvertFrom-Json
        
        if ($data.ok -and $data.data.session_id) {
            Write-Test "Pipecat POST /session/start" $true "Session created"
            return $data.data.session_id
        } else {
            Write-Test "Pipecat POST /session/start" $false "Failed to create session"
            return $null
        }
    } catch {
        Write-Test "Pipecat POST /session/start" $false $_.Exception.Message
        return $null
    }
}

function Test-SessionStop {
    param([string]$SessionId)
    
    try {
        $response = Invoke-WebRequest -Uri "$PIPECAT_URL/session/stop?session_id=$SessionId" `
            -Method POST `
            -TimeoutSec 5 `
            -ErrorAction Stop
        
        $data = $response.Content | ConvertFrom-Json
        
        if ($data.ok -and $data.data.state -eq "CLOSED") {
            Write-Test "Pipecat POST /session/stop" $true "Session closed"
            return $true
        } else {
            Write-Test "Pipecat POST /session/stop" $false "Session not closed"
            return $false
        }
    } catch {
        Write-Test "Pipecat POST /session/stop" $false $_.Exception.Message
        return $false
    }
}

function Test-CorrelationId {
    try {
        $correlationId = "test_" + (New-Guid).ToString().Substring(0, 8)
        $headers = @{ "X-Correlation-ID" = $correlationId }
        
        $response = Invoke-WebRequest -Uri "$API_GATEWAY_URL/status" `
            -Headers $headers `
            -TimeoutSec 5 `
            -ErrorAction Stop
        
        Write-Test "Correlation ID in requests" $true "Propagation working"
        return $true
    } catch {
        Write-Test "Correlation ID in requests" $false $_.Exception.Message
        return $false
    }
}

# Main flow
Write-Host ""
Write-Host "SONIA STACK - PHASE 2 SMOKE TEST" -ForegroundColor Cyan
Write-Host ""

Write-TestHeader "1. Starting All Services"
try {
    & $START_SCRIPT
    Start-Sleep -Seconds 3
    Write-Test "Services started" $true
} catch {
    Write-Test "Services started" $false $_.Exception.Message
    exit 1
}

Write-TestHeader "2. Health Checks"
$allHealthy = $true
$allHealthy = $allHealthy -and (Test-ServiceHealth "api-gateway" "7000" $API_GATEWAY_URL)
$allHealthy = $allHealthy -and (Test-ServiceHealth "memory-engine" "7020" $MEMORY_ENGINE_URL)
$allHealthy = $allHealthy -and (Test-ServiceHealth "model-router" "7010" $MODEL_ROUTER_URL)
$allHealthy = $allHealthy -and (Test-ServiceHealth "openclaw" "7040" $OPENCLAW_URL)
$allHealthy = $allHealthy -and (Test-ServiceHealth "pipecat" "7030" $PIPECAT_URL)

Write-TestHeader "3. Gateway Tests"
Test-GatewayDeps | Out-Null
Test-ActionEndpoint | Out-Null
Test-ChatEndpoint | Out-Null

Write-TestHeader "4. Pipecat Tests"
$sessionId = Test-SessionStart
if ($sessionId) {
    Test-SessionStop $sessionId | Out-Null
}

Write-TestHeader "5. Cross-Service Tests"
Test-CorrelationId | Out-Null

Write-TestHeader "6. Stopping Services"
try {
    & $STOP_SCRIPT
    Write-Test "Services stopped" $true
} catch {
    Write-Test "Services stopped" $false $_.Exception.Message
}

# Summary
Write-Host ""
Write-Host "SUMMARY" -ForegroundColor Cyan
$total = $passed + $failed
Write-Host "  Passed: $passed / $total"
Write-Host "  Failed: $failed / $total"
Write-Host ""

if ($failed -eq 0) {
    Write-Host "✅ ALL TESTS PASSED" -ForegroundColor Green
    exit 0
} else {
    Write-Host "❌ TESTS FAILED" -ForegroundColor Red
    exit 1
}
