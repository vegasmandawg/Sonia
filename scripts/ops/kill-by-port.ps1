Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ports = @(7000, 7010, 7020, 7030, 7040, 7050)
$killed = 0

foreach ($port in $ports) {
    $conn = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    if ($conn) {
        foreach ($c in $conn) {
            $ownerPid = $c.OwningProcess
            Write-Host "Port $port -> PID $ownerPid  (killing)"
            Stop-Process -Id $ownerPid -Force -ErrorAction SilentlyContinue
            $killed++
        }
    } else {
        Write-Host "Port $port -> free"
    }
}

Write-Host "`nKilled $killed process(es)."
