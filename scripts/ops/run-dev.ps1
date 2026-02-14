[CmdletBinding()]
param(
    [string]$Root = "S:\",
    [switch]$RecreateEnv,
    [switch]$NoInstall
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if (-not $Root.EndsWith("\")) { $Root = "$Root\" }

$envPath = Join-Path $Root "envs\sonia-core"
$pyExe   = Join-Path $envPath "python.exe"
$logDir  = Join-Path $Root "logs\services"
$pidDir  = Join-Path $Root "state\pids"

New-Item -ItemType Directory -Force -Path $logDir | Out-Null
New-Item -ItemType Directory -Force -Path $pidDir | Out-Null

function Get-CondaExe {
    $cmd = Get-Command conda -ErrorAction SilentlyContinue
    if ($cmd -and $cmd.Source) { return $cmd.Source }

    $candidates = @(
        "$env:USERPROFILE\miniconda3\Scripts\conda.exe",
        "$env:USERPROFILE\anaconda3\Scripts\conda.exe",
        "C:\ProgramData\miniconda3\Scripts\conda.exe",
        "C:\ProgramData\anaconda3\Scripts\conda.exe"
    )
    foreach ($c in $candidates) {
        if (Test-Path $c) { return $c }
    }
    return $null
}

if ($RecreateEnv -and (Test-Path $envPath)) {
    Write-Host "Removing env: $envPath"
    Remove-Item -Recurse -Force $envPath
}

if (-not (Test-Path $pyExe)) {
    $condaExe = Get-CondaExe
    if (-not $condaExe) {
        throw "conda.exe not found. Install Miniconda/Anaconda or add conda to PATH."
    }

    Write-Host "Creating env at: $envPath"
    & $condaExe create -y -p $envPath python=3.11
}

if (-not $NoInstall) {
    Write-Host "Installing Python dependencies..."
    & $pyExe -m pip install --upgrade pip
    & $pyExe -m pip install fastapi==0.116.1 uvicorn==0.35.0 pydantic==2.11.7
}

$services = @(
    @{ Name = "api-gateway";  Port = 7000; AppDir = (Join-Path $Root "services\api-gateway") },
    @{ Name = "model-router"; Port = 7010; AppDir = (Join-Path $Root "services\model-router") },
    @{ Name = "memory-engine";Port = 7020; AppDir = (Join-Path $Root "services\memory-engine") },
    @{ Name = "pipecat";      Port = 7030; AppDir = (Join-Path $Root "services\pipecat") },
    @{ Name = "openclaw";     Port = 7040; AppDir = (Join-Path $Root "services\openclaw") },
    @{ Name = "eva-os";      Port = 7050; AppDir = (Join-Path $Root "services\eva-os") }
)

# Stop existing processes from previous run (if PID files exist)
foreach ($svc in $services) {
    $pidFile = Join-Path $pidDir "$($svc.Name).pid"
    if (Test-Path $pidFile) {
        $oldPid = Get-Content $pidFile -ErrorAction SilentlyContinue
        if ($oldPid) {
            try {
                Stop-Process -Id ([int]$oldPid) -Force -ErrorAction Stop
                Write-Host "Stopped old $($svc.Name) PID $oldPid"
            } catch {
                # Ignore stale PID
            }
        }
        Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
    }
}

Write-Host "Starting services..."

foreach ($svc in $services) {
    if (-not (Test-Path $svc.AppDir)) {
        throw "Missing app dir for $($svc.Name): $($svc.AppDir)"
    }

    $outLog = Join-Path $logDir "$($svc.Name).out.log"
    $errLog = Join-Path $logDir "$($svc.Name).err.log"
    $pidFile = Join-Path $pidDir "$($svc.Name).pid"

    $cmd = "& `"$pyExe`" -m uvicorn main:app --host 127.0.0.1 --port $($svc.Port) --app-dir `"$($svc.AppDir)`""

    $proc = Start-Process `
        -FilePath "powershell.exe" `
        -ArgumentList "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", $cmd `
        -WindowStyle Hidden `
        -PassThru `
        -RedirectStandardOutput $outLog `
        -RedirectStandardError $errLog

    Set-Content -LiteralPath $pidFile -Value $proc.Id -Encoding ASCII
    Write-Host (" -> {0,-12} PID {1} Port {2}" -f $svc.Name, $proc.Id, $svc.Port)
}

# Health checks
Write-Host ""
Write-Host "Health checks:"
foreach ($svc in $services) {
    $ok = $false
    $url = "http://127.0.0.1:$($svc.Port)/healthz"
    for ($i=0; $i -lt 20; $i++) {
        try {
            $resp = Invoke-RestMethod -Uri $url -Method Get -TimeoutSec 2
            if ($resp.ok -eq $true) { $ok = $true; break }
        } catch {
            Start-Sleep -Milliseconds 300
        }
    }

    if ($ok) {
        Write-Host (" [OK]   {0}  {1}" -f $svc.Name, $url)
    } else {
        Write-Host (" [FAIL] {0}  {1}" -f $svc.Name, $url)
    }
}

Write-Host ""
Write-Host "Done. Logs: $logDir"
Write-Host "PIDs: $pidDir"
