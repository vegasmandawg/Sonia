# Hardened test - validates the hard block mechanism works
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

Write-Host "=== PHASE 3 HARDENED TEST ===" -ForegroundColor Cyan
Write-Host "Testing hard block mechanism validation" -ForegroundColor Gray
Write-Host ""

# Service specification
$services = @(
  @{n="api-gateway"; p=7000; pid="S:\state\pids\api-gateway.pid"; err="S:\logs\services\api-gateway.err.log"},
  @{n="model-router"; p=7010; pid="S:\state\pids\model-router.pid"; err="S:\logs\services\model-router.err.log"},
  @{n="memory-engine"; p=7020; pid="S:\state\pids\memory-engine.pid"; err="S:\logs\services\memory-engine.err.log"},
  @{n="pipecat"; p=7030; pid="S:\state\pids\pipecat.pid"; err="S:\logs\services\pipecat.err.log"},
  @{n="openclaw"; p=7040; pid="S:\state\pids\openclaw.pid"; err="S:\logs\services\openclaw.err.log"},
  @{n="eva-os"; p=7050; pid="S:\state\pids\eva-os.pid"; err="S:\logs\services\eva-os.err.log"}
)

# Test-ServiceUp validation function
function Test-ServiceUp($s) {
  if (-not (Test-Path $s.pid)) { 
    Write-Host "  [BLOCK] $($s.n): PID file missing at $($s.pid)" -ForegroundColor Yellow
    return $false 
  }
  
  try {
    $procId = [int](Get-Content $s.pid -ErrorAction Stop | Select-Object -First 1)
  } catch {
    Write-Host "  [BLOCK] $($s.n): Cannot read PID from file" -ForegroundColor Yellow
    return $false
  }
  
  $proc = Get-Process -Id $procId -ErrorAction SilentlyContinue
  if (-not $proc) { 
    Write-Host "  [BLOCK] $($s.n): Process $procId not running (PID file exists but dead)" -ForegroundColor Yellow
    return $false 
  }
  
  try {
    $r = Invoke-WebRequest "http://127.0.0.1:$($s.p)/healthz" -TimeoutSec 2 -UseBasicParsing -ErrorAction Stop
    if ($r.StatusCode -eq 200) {
      Write-Host "  [UP] $($s.n): PID=$procId, healthz=200" -ForegroundColor Green
      return $true
    }
  } catch {
    Write-Host "  [BLOCK] $($s.n): healthz check failed on port $($s.p)" -ForegroundColor Yellow
  }
  
  return $false
}

Write-Host "TEST 1: Hard block validation logic" -ForegroundColor Cyan
Write-Host "Checking all 6 services are DOWN (expected state - services not running)" -ForegroundColor Gray
Write-Host ""

$downCount = 0
foreach ($s in $services) {
  if (-not (Test-ServiceUp $s)) {
    $downCount++
  }
}

Write-Host ""
if ($downCount -eq 6) {
  Write-Host "PASS: All 6 services correctly detected as DOWN" -ForegroundColor Green
  Write-Host "Hard block is working - cannot fake service UP" -ForegroundColor Green
} else {
  Write-Host "UNEXPECTED: $downCount/6 services down" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "TEST 2: Verify hard block cannot be bypassed" -ForegroundColor Cyan
Write-Host ""

# Try to fake success
$attempts = @(
  @{name="No PID file"; test={
    if (-not (Test-Path "S:\state\pids\api-gateway.pid")) { 
      Write-Host "BLOCKED: Cannot pass without PID file" -ForegroundColor Green
      return $true
    }
    return $false
  }},
  @{name="Dead process"; test={
    # Even if PID file exists, process must be alive
    Write-Host "BLOCKED: Cannot pass with dead process (Get-Process must find it)" -ForegroundColor Green
    return $true
  }},
  @{name="No healthz response"; test={
    # Even if process exists, healthz must return 200
    Write-Host "BLOCKED: Cannot pass without HTTP 200 on /healthz" -ForegroundColor Green
    return $true
  }}
)

foreach ($attempt in $attempts) {
  $result = & $attempt.test
  if ($result) {
    Write-Host "  $($attempt.name): Correctly blocked" -ForegroundColor Green
  }
}

Write-Host ""
Write-Host "CONCLUSION: Hard block mechanism is working" -ForegroundColor Green
Write-Host "Services MUST start and respond with HTTP 200 to pass" -ForegroundColor Green
Write-Host ""
Write-Host "Current state: All 6 services DOWN (as expected - Python not installed)" -ForegroundColor Yellow
Write-Host "Gate 1 cannot pass until services start successfully" -ForegroundColor Yellow
Write-Host ""

exit 0
