<#
.SYNOPSIS
Sonia Stack Helper Library

.DESCRIPTION
Common functions for starting and stopping Sonia services.
Provides service management, directory utilities, and health checks.

Usage:
  . .\scripts\lib\sonia-stack.ps1
  Start-SoniaService -Name "API Gateway" -ServiceDir "S:\backend\services\api-gateway" -Port 7000 -PidFile "S:\state\pids\api-gateway.pid"
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# ─────────────────────────────────────────────────────────────────────────────
# Helper Functions
# ─────────────────────────────────────────────────────────────────────────────

<#
.SYNOPSIS
Get canonical Sonia root directory with intelligent fallback.

.PARAMETER HintRoot
Optional hint path to use as starting point. If not provided, uses current directory.

.OUTPUTS
[string] Canonical root directory ending with backslash
#>
function Get-SoniaRoot {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory=$false)]
        [string]$HintRoot
    )

    # Try hint first
    if ($HintRoot -and (Test-Path -LiteralPath $HintRoot)) {
        $root = $HintRoot
    }
    # Try S:\ (canonical location)
    elseif (Test-Path "S:\") {
        $root = "S:\"
    }
    # Try environment variable
    elseif ($env:SONIA_ROOT -and (Test-Path -LiteralPath $env:SONIA_ROOT)) {
        $root = $env:SONIA_ROOT
    }
    # Fall back to current directory
    else {
        $root = (Get-Location).Path
    }

    # Normalize: ensure trailing backslash
    if (-not $root.EndsWith("\")) { $root = "$root\" }
    
    return $root
}

<#
.SYNOPSIS
Ensure a directory exists, creating if necessary.

.PARAMETER Path
Directory path to ensure exists.

.OUTPUTS
[string] The normalized directory path
#>
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

<#
.SYNOPSIS
Start a Sonia service using uvicorn.

.PARAMETER Name
Display name of the service (e.g., "API Gateway").

.PARAMETER ServiceDir
Full path to service directory containing main.py.

.PARAMETER Port
Port number for the service (e.g., 7000).

.PARAMETER PidFile
Full path where to write the process ID file.

.PARAMETER Host
Host to bind to. Defaults to 127.0.0.1.

.PARAMETER Reload
If specified, enable auto-reload on file changes (development mode).

.OUTPUTS
[int] Process ID of started service, or 0 if failed

.EXAMPLE
Start-SoniaService -Name "API Gateway" -ServiceDir "S:\backend\services\api-gateway" -Port 7000 -PidFile "S:\state\pids\api-gateway.pid"
#>
function Start-SoniaService {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory=$true)]
        [string]$Name,

        [Parameter(Mandatory=$true)]
        [string]$ServiceDir,

        [Parameter(Mandatory=$true)]
        [int]$Port,

        [Parameter(Mandatory=$true)]
        [string]$PidFile,

        [Parameter(Mandatory=$false)]
        [string]$BindHost = "127.0.0.1",

        [Parameter(Mandatory=$false)]
        [switch]$Reload
    )

    # Validate service directory
    if (-not (Test-Path -LiteralPath $ServiceDir -PathType Container)) {
        Write-Error "Service directory not found: $ServiceDir"
        return 0
    }

    # Check for main.py
    $mainPy = Join-Path $ServiceDir "main.py"
    if (-not (Test-Path -LiteralPath $mainPy)) {
        Write-Error "main.py not found in $ServiceDir"
        return 0
    }

    # Ensure PID directory exists
    $pidDir = Split-Path -Parent $PidFile
    Ensure-Dir $pidDir | Out-Null

    # Build uvicorn command with proper working directory
    $reloadFlag = if ($Reload) { "--reload" } else { "" }
    $cmd = "cd `"$ServiceDir`"; python -m uvicorn main:app --host $BindHost --port $Port $reloadFlag"

    # Start process
    try {
        $proc = Start-Process `
            -FilePath "powershell.exe" `
            -ArgumentList "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", $cmd `
            -WindowStyle Hidden `
            -PassThru

        $procId = $proc.Id
        
        # Write PID file
        Set-Content -LiteralPath $PidFile -Value $procId -Encoding ASCII -Force
        
        Write-Host "[✓] $Name started (PID $procId, port $Port)"
        return $procId
    }
    catch {
        Write-Error "Failed to start $Name : $_"
        return 0
    }
}

<#
.SYNOPSIS
Stop a Sonia service by PID file.

.PARAMETER PidFile
Path to PID file containing process ID.

.PARAMETER Timeout
Seconds to wait for graceful shutdown before force kill. Defaults to 10.

.OUTPUTS
[bool] $true if stopped successfully, $false otherwise

.EXAMPLE
Stop-SoniaService -PidFile "S:\state\pids\api-gateway.pid"
#>
function Stop-SoniaService {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory=$true)]
        [string]$PidFile,

        [Parameter(Mandatory=$false)]
        [int]$Timeout = 10
    )

    # Check if PID file exists
    if (-not (Test-Path -LiteralPath $PidFile)) {
        Write-Host "[~] PID file not found: $PidFile"
        return $true
    }

    # Read PID
    try {
        $procId = [int](Get-Content -LiteralPath $PidFile -Raw).Trim()
    }
    catch {
        Write-Error "Failed to read PID from $PidFile : $_"
        return $false
    }

    # Check if process exists
    $proc = Get-Process -Id $procId -ErrorAction SilentlyContinue
    if (-not $proc) {
        Write-Host "[~] Process $procId not running; cleaning up PID file"
        Remove-Item -LiteralPath $PidFile -Force -ErrorAction SilentlyContinue
        return $true
    }

    # Attempt graceful shutdown
    Write-Host "[*] Stopping process $procId (timeout: $Timeout seconds)..."
    try {
        Stop-Process -Id $procId -NoWait
        
        # Wait for graceful shutdown
        $stopwatch = [System.Diagnostics.Stopwatch]::StartNew()
        while ($stopwatch.Elapsed.TotalSeconds -lt $Timeout) {
            $proc = Get-Process -Id $procId -ErrorAction SilentlyContinue
            if (-not $proc) {
                Write-Host "[✓] Process $procId stopped gracefully"
                Remove-Item -LiteralPath $PidFile -Force -ErrorAction SilentlyContinue
                return $true
            }
            Start-Sleep -Milliseconds 100
        }

        # Force kill if still running
        Write-Host "[!] Process $procId not responding; force killing..."
        Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
        Start-Sleep -Milliseconds 500

        # Verify killed
        $proc = Get-Process -Id $procId -ErrorAction SilentlyContinue
        if ($proc) {
            Write-Error "Failed to kill process $procId"
            return $false
        }

        Write-Host "[✓] Process $procId force killed"
        Remove-Item -LiteralPath $PidFile -Force -ErrorAction SilentlyContinue
        return $true
    }
    catch {
        Write-Error "Error stopping process $procId : $_"
        return $false
    }
}

<#
.SYNOPSIS
Check service health via HTTP endpoint.

.PARAMETER Host
Service host. Defaults to 127.0.0.1.

.PARAMETER Port
Service port.

.PARAMETER Endpoint
Health endpoint path. Defaults to /healthz.

.PARAMETER Timeout
Request timeout in seconds. Defaults to 3.

.OUTPUTS
[bool] $true if service is healthy, $false otherwise

.EXAMPLE
Test-SoniaServiceHealth -Port 7000
#>
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

    $url = "http://$BindHost`:$Port$Endpoint"
    
    try {
        $response = Invoke-WebRequest -Uri $url -TimeoutSec $Timeout -UseBasicParsing -ErrorAction Stop
        return $response.StatusCode -eq 200
    }
    catch {
        return $false
    }
}

<#
.SYNOPSIS
Wait for a service to become healthy.

.PARAMETER Port
Service port.

.PARAMETER MaxWaitSeconds
Maximum time to wait. Defaults to 30.

.PARAMETER CheckIntervalMs
Interval between checks in milliseconds. Defaults to 500.

.OUTPUTS
[bool] $true if service became healthy, $false if timeout

.EXAMPLE
Wait-SoniaServiceHealth -Port 7000 -MaxWaitSeconds 20
#>
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

# Functions are available when dot-sourced as a script
# (Export-ModuleMember only works when imported as a module, not when dot-sourced)
