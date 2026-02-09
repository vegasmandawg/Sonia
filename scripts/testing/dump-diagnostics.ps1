Set-StrictMode -Version Latest

Write-Host "=== PID FILES ==="
Get-ChildItem "S:\state\pids\*.pid" -ErrorAction SilentlyContinue | ForEach-Object {
    $content = Get-Content $_.FullName -ErrorAction SilentlyContinue
    Write-Host "$($_.Name): $content"
}

Write-Host ""
Write-Host "=== LISTENING PORTS (7000-7050) ==="
Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
    Where-Object { $_.LocalPort -in @(7000,7010,7020,7030,7040,7050) } |
    Format-Table LocalAddress,LocalPort,OwningProcess -AutoSize

Write-Host ""
Write-Host "=== ERR LOG TAILS (last 30 lines each) ==="
Get-ChildItem "S:\logs\services\*.err.log" -ErrorAction SilentlyContinue | ForEach-Object {
    Write-Host "--- $($_.Name) ---"
    Get-Content $_.FullName -Tail 30
    Write-Host ""
}
