Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Test-PortListen {
    param([int]$Port)
    return [bool](Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
}

function Start-SoniaService {
    param(
        [Parameter(Mandatory)][string]$ServiceName,
        [Parameter(Mandatory)][string]$ServiceDir,
        [Parameter(Mandatory)][int]$Port,
        [string]$PythonExe = "S:\envs\sonia-core\python.exe",
        [string]$BindHost = "127.0.0.1",
        [int]$BootWaitSeconds = 8
    )

    $slug   = $ServiceName.ToLower()
    $pidDir = "S:\state\pids"
    $logDir = "S:\logs\services"
    New-Item -ItemType Directory -Path $pidDir -Force | Out-Null
    New-Item -ItemType Directory -Path $logDir -Force | Out-Null

    $pidFile = Join-Path $pidDir "$slug.pid"
    $outLog  = Join-Path $logDir "$slug.out.log"
    $errLog  = Join-Path $logDir "$slug.err.log"

    Remove-Item $pidFile -Force -ErrorAction SilentlyContinue

    if (-not (Test-Path $PythonExe)) { throw "Python not found: $PythonExe" }
    if (-not (Test-Path $ServiceDir)) { throw "Service dir missing: $ServiceDir" }

    $args = @("-m","uvicorn","main:app","--host",$BindHost,"--port",$Port.ToString())

    $proc = Start-Process -FilePath $PythonExe `
        -ArgumentList $args `
        -WorkingDirectory $ServiceDir `
        -RedirectStandardOutput $outLog `
        -RedirectStandardError  $errLog `
        -WindowStyle Hidden `
        -PassThru

    Set-Content -Path $pidFile -Value ([string]$proc.Id) -Encoding ASCII

    $deadline = (Get-Date).AddSeconds($BootWaitSeconds)
    do {
        if ($proc.HasExited) {
            $tail = if (Test-Path $errLog) { Get-Content $errLog -Tail 60 | Out-String } else { "<no log>" }
            throw "$ServiceName exited early.`n$tail"
        }
        if (Test-PortListen -Port $Port) { return $proc.Id }
        Start-Sleep -Milliseconds 250
    } while ((Get-Date) -lt $deadline)

    $tail = if (Test-Path $errLog) { Get-Content $errLog -Tail 60 | Out-String } else { "<no log>" }
    throw "$ServiceName failed to listen on :$Port within $BootWaitSeconds sec.`n$tail"
}

function Stop-SoniaService {
    param(
        [Parameter(Mandatory)][string]$ServiceName,
        [int]$Port = 0
    )
    $slug = $ServiceName.ToLower()
    $pidFile = "S:\state\pids\$slug.pid"

    # Primary: kill by PID file
    if (Test-Path $pidFile) {
        try {
            $procId = [int](Get-Content $pidFile | Select-Object -First 1)
            Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
        } finally {
            Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
        }
    }

    # Fallback: kill any process still listening on the port
    if ($Port -gt 0) {
        $conn = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
        if ($conn) {
            foreach ($c in $conn) {
                Stop-Process -Id $c.OwningProcess -Force -ErrorAction SilentlyContinue
            }
        }
    }
}
