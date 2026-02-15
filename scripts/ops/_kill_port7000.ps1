$ErrorActionPreference = "Stop"
$cons = Get-NetTCPConnection -LocalPort 7000 -State Listen -ErrorAction SilentlyContinue
if ($cons) {
    $pids = $cons | Select-Object -ExpandProperty OwningProcess -Unique
    foreach ($p in $pids) {
        $proc = Get-Process -Id $p -ErrorAction SilentlyContinue
        Write-Host "Killing PID $p ($($proc.ProcessName))"
        try { Stop-Process -Id $p -Force -ErrorAction Stop } catch { Write-Host "Already gone: $p" }
    }
    Write-Host "Orphan processes terminated"
} else {
    Write-Host "No process listening on port 7000"
}
