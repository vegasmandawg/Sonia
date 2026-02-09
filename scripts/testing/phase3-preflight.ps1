param(
  [int]$StartupTimeoutSeconds = 90
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$services = @(
  @{ Name="api-gateway"; Port=7000; Err="S:\logs\services\api-gateway.err.log" },
  @{ Name="model-router"; Port=7010; Err="S:\logs\services\model-router.err.log" },
  @{ Name="memory-engine"; Port=7020; Err="S:\logs\services\memory-engine.err.log" },
  @{ Name="pipecat"; Port=7030; Err="S:\logs\services\pipecat.err.log" },
  @{ Name="openclaw"; Port=7040; Err="S:\logs\services\openclaw.err.log" },
  @{ Name="eva-os"; Port=7050; Err="S:\logs\services\eva-os.err.log" }
)

function Get-StartScript {
  foreach ($p in @(
    "S:\scripts\ops\start-sonia-stack-v2.ps1",
    "S:\start-sonia-stack.ps1",
    "S:\scripts\ops\start-sonia-stack.ps1"
  )) { if (Test-Path $p) { return $p } }
  throw "No start script found."
}

function Get-StopScript {
  foreach ($p in @(
    "S:\stop-sonia-stack.ps1",
    "S:\scripts\ops\stop-sonia-stack.ps1"
  )) { if (Test-Path $p) { return $p } }
  throw "No stop script found."
}

function Test-Health([int]$port) {
  try {
    $r = Invoke-WebRequest -Uri "http://127.0.0.1:$port/healthz" -TimeoutSec 2 -UseBasicParsing
    return ($r.StatusCode -eq 200)
  } catch { return $false }
}

Write-Host "=== PREFLIGHT: Verifying services via HTTP healthz ==="

# Hard reset stale state
$stop = Get-StopScript
& $stop
Remove-Item "S:\state\pids\*.pid" -Force -ErrorAction SilentlyContinue

# Start stack
$start = Get-StartScript
& $start -SkipHealthCheck

$deadline = (Get-Date).AddSeconds($StartupTimeoutSeconds)
do {
  $ok = 0
  foreach ($s in $services) { if (Test-Health $s.Port) { $ok++ } }
  Write-Host ("[{0}] Healthy {1}/6" -f (Get-Date -Format "HH:mm:ss"), $ok)
  if ($ok -eq 6) {
    Write-Host "PASS: 6/6 services responding"
    exit 0
  }
  Start-Sleep -Seconds 1
} while ((Get-Date) -lt $deadline)

Write-Host "FAIL: Only 0/6..5/6 services responding by timeout"
foreach ($s in $services) {
  $alive = Test-Health $s.Port
  Write-Host ("  {0} (:{1}): {2}" -f $s.Name, $s.Port, $(if($alive){"OK"}else{"NOT RESPONDING"}))
  if (Test-Path $s.Err) {
    Write-Host ("---- tail {0} ----" -f $s.Err)
    Get-Content $s.Err -Tail 40
  }
}
exit 10
