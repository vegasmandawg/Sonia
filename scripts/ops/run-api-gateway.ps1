. "S:\scripts\lib\sonia-stack.ps1"
$servicePid = Start-SoniaService -ServiceName "api-gateway" -ServiceDir "S:\services\api-gateway" -Port 7000
Write-Host "[OK] API Gateway started (PID $servicePid, port 7000)"
$servicePid
