$services = @(
  @{n="api-gateway"; p=7000; pid="S:\state\pids\api-gateway.pid"; out="S:\logs\services\api-gateway.out.log"; err="S:\logs\services\api-gateway.err.log"},
  @{n="model-router"; p=7010; pid="S:\state\pids\model-router.pid"; out="S:\logs\services\model-router.out.log"; err="S:\logs\services\model-router.err.log"},
  @{n="memory-engine"; p=7020; pid="S:\state\pids\memory-engine.pid"; out="S:\logs\services\memory-engine.out.log"; err="S:\logs\services\memory-engine.err.log"},
  @{n="pipecat"; p=7030; pid="S:\state\pids\pipecat.pid"; out="S:\logs\services\pipecat.out.log"; err="S:\logs\services\pipecat.err.log"},
  @{n="openclaw"; p=7040; pid="S:\state\pids\openclaw.pid"; out="S:\logs\services\openclaw.out.log"; err="S:\logs\services\openclaw.err.log"},
  @{n="eva-os"; p=7050; pid="S:\state\pids\eva-os.pid"; out="S:\logs\services\eva-os.out.log"; err="S:\logs\services\eva-os.err.log"}
)

foreach ($s in $services) {
  Write-Host "`n=== $($s.n) :$($s.p) ===" -ForegroundColor Cyan
  $pidExists = Test-Path $s.pid
  $procId = $null
  $alive = $false
  if ($pidExists) {
    $procId = [int](Get-Content $s.pid | Select-Object -First 1)
    $alive = [bool](Get-Process -Id $procId -ErrorAction SilentlyContinue)
  }
  $listen = [bool](Get-NetTCPConnection -LocalPort $s.p -State Listen -ErrorAction SilentlyContinue)
  $health = $false
  try {
    $r = Invoke-WebRequest "http://127.0.0.1:$($s.p)/healthz" -TimeoutSec 2 -UseBasicParsing
    $health = ($r.StatusCode -eq 200)
  } catch {}
  Write-Host "pidFile=$pidExists pid=$procId alive=$alive listen=$listen health200=$health"

  if (Test-Path $s.err) { 
    Write-Host "-- ERR tail (last 30 lines) --" -ForegroundColor Yellow
    Get-Content $s.err -Tail 30
  }
}
