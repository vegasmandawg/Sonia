. "S:\scripts\lib\sonia-stack.ps1"
$servicePid = Start-SoniaService -ServiceName "openclaw" -ServiceDir "S:\services\openclaw" -Port 7040
Write-Host "[OK] OpenClaw started (PID $servicePid, port 7040)"
$servicePid
