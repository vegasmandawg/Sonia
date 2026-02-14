. "S:\scripts\lib\sonia-stack.ps1"
$servicePid = Start-SoniaService -ServiceName "perception" -ServiceDir "S:\services\perception" -Port 7070
Write-Host "[OK] Perception started (PID $servicePid, port 7070)"
$servicePid
