# Preflight: Verify services are healthy via HTTP only
# Services are running but may not write PID files

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$services = @(
  @{name="api-gateway"; port=7000},
  @{name="model-router"; port=7010},
  @{name="memory-engine"; port=7020},
  @{name="pipecat"; port=7030},
  @{name="openclaw"; port=7040},
  @{name="eva-os"; port=7050}
)

Write-Host "=== PREFLIGHT: Verifying services via HTTP healthz ===" -ForegroundColor Cyan
Write-Host ""

$healthy_count = 0
$timeout_sec = 90
$start_time = Get-Date
$deadline = $start_time.AddSeconds($timeout_sec)

# Try to reach all services within timeout
while ((Get-Date) -lt $deadline) {
  $healthy_count = 0
  
  foreach ($svc in $services) {
    try {
      $response = Invoke-WebRequest "http://127.0.0.1:$($svc.port)/healthz" `
        -TimeoutSec 2 `
        -UseBasicParsing `
        -ErrorAction SilentlyContinue
      
      if ($response.StatusCode -eq 200) {
        $healthy_count++
      }
    } catch {
      # Service not responding yet
    }
  }
  
  if ($healthy_count -eq $services.Count) {
    break
  }
  
  Start-Sleep -Seconds 1
}

# Report results
Write-Host ""
foreach ($svc in $services) {
  try {
    $response = Invoke-WebRequest "http://127.0.0.1:$($svc.port)/healthz" `
      -TimeoutSec 2 `
      -UseBasicParsing `
      -ErrorAction SilentlyContinue
    
    if ($response.StatusCode -eq 200) {
      Write-Host "  $($svc.name) (:$($svc.port)): HEALTHY" -ForegroundColor Green
    } else {
      Write-Host "  $($svc.name) (:$($svc.port)): UNHEALTHY (HTTP $($response.StatusCode))" -ForegroundColor Red
    }
  } catch {
    Write-Host "  $($svc.name) (:$($svc.port)): NOT RESPONDING" -ForegroundColor Red
  }
}

Write-Host ""
if ($healthy_count -eq $services.Count) {
  Write-Host "PASS: All $($services.Count) services healthy" -ForegroundColor Green
  exit 0
} else {
  Write-Host "FAIL: Only $healthy_count/$($services.Count) services responding" -ForegroundColor Red
  exit 1
}
