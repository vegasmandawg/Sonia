. "S:\scripts\lib\sonia-stack.ps1"
$servicePid = Start-SoniaService -ServiceName "model-router" -ServiceDir "S:\services\model-router" -Port 7010
Write-Host "[OK] Model Router started (PID $servicePid, port 7010)"
$servicePid
