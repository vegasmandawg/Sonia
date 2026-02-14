Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# ─────────────────────────────────────────────────────────────────────────────
# Utility Functions
# ─────────────────────────────────────────────────────────────────────────────

function Get-SoniaRoot {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory=$false)]
        [string]$HintRoot
    )
    if ($HintRoot -and (Test-Path -LiteralPath $HintRoot)) {
        $root = $HintRoot
    }
    elseif (Test-Path "S:\") {
        $root = "S:\"
    }
    elseif ($env:SONIA_ROOT -and (Test-Path -LiteralPath $env:SONIA_ROOT)) {
        $root = $env:SONIA_ROOT
    }
    else {
        $root = (Get-Location).Path
    }
    if (-not $root.EndsWith("\")) { $root = "$root\" }
    return $root
}

function Ensure-Dir {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory=$true)]
        [string]$Path
    )
    if (-not (Test-Path -LiteralPath $Path -PathType Container)) {
        New-Item -ItemType Directory -Path $Path -Force | Out-Null
    }
    return $Path
}

# ─────────────────────────────────────────────────────────────────────────────
# Port / Health Functions
# ─────────────────────────────────────────────────────────────────────────────

function Test-PortListen {
    param([int]$Port)
    return [bool](Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
}

function Test-SoniaServiceHealth {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory=$false)]
        [string]$BindHost = "127.0.0.1",

        [Parameter(Mandatory=$true)]
        [int]$Port,

        [Parameter(Mandatory=$false)]
        [string]$Endpoint = "/healthz",

        [Parameter(Mandatory=$false)]
        [int]$Timeout = 3
    )
    $url = "http://${BindHost}:${Port}${Endpoint}"
    try {
        $response = Invoke-WebRequest -Uri $url -TimeoutSec $Timeout -UseBasicParsing -ErrorAction Stop
        return $response.StatusCode -eq 200
    }
    catch {
        return $false
    }
}

function Wait-SoniaServiceHealth {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory=$true)]
        [int]$Port,

        [Parameter(Mandatory=$false)]
        [int]$MaxWaitSeconds = 30,

        [Parameter(Mandatory=$false)]
        [int]$CheckIntervalMs = 500
    )
    $stopwatch = [System.Diagnostics.Stopwatch]::StartNew()
    while ($stopwatch.Elapsed.TotalSeconds -lt $MaxWaitSeconds) {
        if (Test-SoniaServiceHealth -Port $Port) {
            return $true
        }
        Start-Sleep -Milliseconds $CheckIntervalMs
    }
    return $false
}

# ─────────────────────────────────────────────────────────────────────────────
# Service Lifecycle
# ─────────────────────────────────────────────────────────────────────────────

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

    # NOTE: Do NOT use $args here — it is a read-only automatic variable in PowerShell
    $uvicornArgs = @("-m","uvicorn","main:app","--host",$BindHost,"--port",$Port.ToString())

    $proc = Start-Process -FilePath $PythonExe `
        -ArgumentList $uvicornArgs `
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
            # Wait up to 3s for process to exit
            for ($i = 0; $i -lt 12; $i++) {
                $still = Get-Process -Id $procId -ErrorAction SilentlyContinue
                if (-not $still) { break }
                Start-Sleep -Milliseconds 250
            }
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
