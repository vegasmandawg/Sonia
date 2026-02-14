[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

. "S:\scripts\lib\sonia-stack.ps1"

Write-Host ""
Write-Host "Stopping Sonia Stack..." -ForegroundColor Cyan

# Stop in reverse order (name -> port)
$services = @(
    @{ Name="mcp-server";    Port=8080 },
    @{ Name="perception";    Port=7070 },
    @{ Name="vision-capture"; Port=7060 },
    @{ Name="eva-os";        Port=7050 },
    @{ Name="openclaw";      Port=7040 },
    @{ Name="pipecat";       Port=7030 },
    @{ Name="memory-engine"; Port=7020 },
    @{ Name="model-router";  Port=7010 },
    @{ Name="api-gateway";   Port=7000 }
)

$stopped = 0
foreach ($svc in $services) {
    try {
        Stop-SoniaService -ServiceName $svc.Name -Port $svc.Port
        Write-Host "[OK] Stopped $($svc.Name)" -ForegroundColor Green
        $stopped++
    } catch {
        Write-Host "[WARN] Failed to stop $($svc.Name) : $_" -ForegroundColor Yellow
    }
}

Write-Host ""
Write-Host "Shutdown complete. Stopped $stopped service(s)." -ForegroundColor Green
