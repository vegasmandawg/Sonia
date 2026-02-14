. "S:\scripts\lib\sonia-stack.ps1"
$servicePid = Start-SoniaService -ServiceName "vision-capture" -ServiceDir "S:\services\vision-capture" -Port 7060
Write-Host "[OK] Vision Capture started (PID $servicePid, port 7060)"
$servicePid
