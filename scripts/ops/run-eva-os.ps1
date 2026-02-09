. "S:\scripts\lib\sonia-stack.ps1"
$servicePid = Start-SoniaService -ServiceName "eva-os" -ServiceDir "S:\services\eva-os" -Port 7050
Write-Host "[OK] EVA-OS started (PID $servicePid, port 7050)"
$servicePid
