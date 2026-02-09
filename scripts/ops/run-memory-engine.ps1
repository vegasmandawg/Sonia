. "S:\scripts\lib\sonia-stack.ps1"
$servicePid = Start-SoniaService -ServiceName "memory-engine" -ServiceDir "S:\services\memory-engine" -Port 7020
Write-Host "[OK] Memory Engine started (PID $servicePid, port 7020)"
$servicePid
