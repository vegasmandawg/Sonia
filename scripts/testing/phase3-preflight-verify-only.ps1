# Preflight: Verify services are healthy (do not restart)
# Services are already running; this just validates they're responsive

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$services = @(
  @{n="api-gateway"; p=7000; pid="S:\state\pids\api-gateway.pid"; err="S:\logs\services\api-gateway.err.log"},
  @{n="model-router"; p=7010; pid="S:\state\pids\model-router.pid"; err="S:\logs\services\model-router.err.log"},
  @{n="memory-engine"; p=7020; pid="S:\state\pids\memory-engine.pid"; err="S:\logs\services\memory-engine.err.log"},
  @{n="pipecat"; p=7030; pid="S:\state\pids\pipecat.pid"; err="S:\logs\services\pipecat.err.log"},
  @{n="openclaw"; p=7040; pid="S:\state\pids\openclaw.pid"; err="S:\logs\services\openclaw.err.log"},
  @{n="eva-os"; p=7050; pid="S:\state\pids\eva-os.pid"; err="S:\logs\services\eva-os.err.log"}
)

function Test-ServiceUp($s) {
  if (-not (Test-Path $s.pid)) { 
    Write-Host "  $($s.n): PID file missing" -ForegroundColor Red
    return $false 
  }
  
  try {
    $procId = [int](Get-Content $s.pid | Select-Object -First 1)
  } catch {
    Write-Host "  $($s.n): Cannot read PID from $($s.pid)" -ForegroundColor Red
    return $false
  }
  
  if (-not (Get-Process -Id $procId -ErrorAction SilentlyContinue)) { 
    Write-Host "  $($s.n): Process $procId not running" -ForegroundColor Red
    return $false 
  }
  
  try {
    $r = Invoke-WebRequest "http://127.0.0.1:$($s.p)/healthz" -TimeoutSec 2 -UseBasicParsing -ErrorAction SilentlyContinue
    if ($r.StatusCode -eq 200) {
      Write-Host "  $($s.n): HEALTHY (PID $procId, /healthz 200)" -ForegroundColor Green
      return $true
    }
  } catch { }
  
  Write-Host "  $($s.n): Healthz check failed" -ForegroundColor Red
  return $false
}

Write-Host "=== PREFLIGHT: Verifying services are healthy ===" -ForegroundColor Cyan
Write-Host ""

$healthy_count = 0
foreach ($s in $services) {
  if (Test-ServiceUp $s) {
    $healthy_count++
  }
}

Write-Host ""
if ($healthy_count -eq $services.Count) {
  Write-Host "PASS: All $($services.Count) services healthy" -ForegroundColor Green
  exit 0
} else {
  Write-Host "FAIL: Only $healthy_count/$($services.Count) services healthy" -ForegroundColor Red
  exit 1
}
