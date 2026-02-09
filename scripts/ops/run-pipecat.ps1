. "S:\scripts\lib\sonia-stack.ps1"
$servicePid = Start-SoniaService -ServiceName "pipecat" -ServiceDir "S:\services\pipecat" -Port 7030
Write-Host "[OK] Pipecat started (PID $servicePid, port 7030)"
$servicePid
