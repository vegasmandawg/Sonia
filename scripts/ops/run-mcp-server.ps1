. "S:\scripts\lib\sonia-stack.ps1"

# MCP server uses SSE transport (not uvicorn), so we launch it directly
$pythonExe = "S:\envs\sonia-core\python.exe"
$serviceDir = "S:\services\mcp-server"
$slug = "mcp-server"
$pidDir = "S:\state\pids"
$logDir = "S:\logs\services"

New-Item -ItemType Directory -Path $pidDir -Force | Out-Null
New-Item -ItemType Directory -Path $logDir -Force | Out-Null

$pidFile = Join-Path $pidDir "$slug.pid"
$outLog  = Join-Path $logDir "$slug.out.log"
$errLog  = Join-Path $logDir "$slug.err.log"

Remove-Item $pidFile -Force -ErrorAction SilentlyContinue

if (-not (Test-Path $pythonExe)) { throw "Python not found: $pythonExe" }
if (-not (Test-Path $serviceDir)) { throw "Service dir missing: $serviceDir" }

$proc = Start-Process -FilePath $pythonExe `
    -ArgumentList @("server.py", "--sse", "--port", "8080") `
    -WorkingDirectory $serviceDir `
    -RedirectStandardOutput $outLog `
    -RedirectStandardError  $errLog `
    -WindowStyle Hidden `
    -PassThru

Set-Content -Path $pidFile -Value ([string]$proc.Id) -Encoding ASCII

# MCP SSE server doesn't have /healthz -- wait for port listen
$deadline = (Get-Date).AddSeconds(10)
do {
    if ($proc.HasExited) {
        $tail = if (Test-Path $errLog) { Get-Content $errLog -Tail 30 | Out-String } else { "<no log>" }
        throw "MCP Server exited early.`n$tail"
    }
    if (Test-PortListen -Port 8080) {
        Write-Host "[OK] MCP Server started (PID $($proc.Id), SSE on port 8080)"
        $proc.Id
        return
    }
    Start-Sleep -Milliseconds 250
} while ((Get-Date) -lt $deadline)

Write-Host "[WARN] MCP Server may still be starting (PID $($proc.Id))" -ForegroundColor Yellow
$proc.Id
