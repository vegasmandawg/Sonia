# === Rebuild Sonia launcher stack (deterministic) ===
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

# 0) Backups
$ts = Get-Date -Format "yyyyMMdd-HHmmss"
Copy-Item "S:\scripts\lib\sonia-stack.ps1" "S:\scripts\lib\sonia-stack.$ts.bak.ps1" -Force -ErrorAction SilentlyContinue
Copy-Item "S:\scripts\ops\start-sonia-stack-v2.ps1" "S:\scripts\ops\start-sonia-stack-v2.$ts.bak.ps1" -Force -ErrorAction SilentlyContinue

# 1) Write clean library
$lib = @'
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Start-SoniaService {
    param(
        [Parameter(Mandatory)] [string] $Name,
        [Parameter(Mandatory)] [string] $ServiceDir,
        [Parameter(Mandatory)] [int] $Port,
        [string] $PythonExe = "S:\tools\python\python.exe"
    )

    $pidDir = "S:\state\pids"
    $logDir = "S:\logs\services"
    New-Item -ItemType Directory -Path $pidDir -Force | Out-Null
    New-Item -ItemType Directory -Path $logDir -Force | Out-Null

    if (-not (Test-Path $PythonExe)) { throw "Python not found: $PythonExe" }
    if (-not (Test-Path $ServiceDir)) { throw "ServiceDir not found: $ServiceDir" }

    $slug = $Name.ToLower().Replace(' ','-')
    $pidFile = Join-Path $pidDir "$slug.pid"
    $outLog  = Join-Path $logDir "$slug.out.log"
    $errLog  = Join-Path $logDir "$slug.err.log"

    # clear stale pid
    if (Test-Path $pidFile) { Remove-Item $pidFile -Force -ErrorAction SilentlyContinue }

    $args = @("-m","uvicorn","main:app","--host","127.0.0.1","--port",$Port.ToString())
    $p = Start-Process -FilePath $PythonExe `
        -ArgumentList $args `
        -WorkingDirectory $ServiceDir `
        -RedirectStandardOutput $outLog `
        -RedirectStandardError $errLog `
        -PassThru -WindowStyle Hidden

    Start-Sleep -Seconds 1
    if ($p.HasExited) {
        $tail = if (Test-Path $errLog) { (Get-Content $errLog -Tail 40 | Out-String) } else { "<no err log>" }
        throw "Service '$Name' exited immediately.`n$tail"
    }

    Set-Content -Path $pidFile -Value $p.Id -Encoding ASCII
    return $p.Id
}

function Stop-SoniaService {
    param([Parameter(Mandatory)] [string] $Name)
    $slug = $Name.ToLower().Replace(' ','-')
    $pidFile = "S:\state\pids\$slug.pid"
    if (Test-Path $pidFile) {
        try {
            $procId = [int](Get-Content $pidFile | Select-Object -First 1)
            Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
        } finally {
            Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
        }
    }
}

function Test-SoniaHealth {
    param([Parameter(Mandatory)] [int] $Port)
    try {
        $r = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/healthz" -TimeoutSec 2
        return ($r.StatusCode -eq 200)
    } catch { return $false }
}
'@
Set-Content "S:\scripts\lib\sonia-stack.ps1" -Value $lib -Encoding UTF8

# 2) Generate run-*.ps1 launchers (all 6, including eva-os)
$services = @(
    @{slug='api-gateway';  name='api-gateway';  dir='S:\services\api-gateway';  port=7000},
    @{slug='model-router'; name='model-router'; dir='S:\services\model-router'; port=7010},
    @{slug='memory-engine';name='memory-engine';dir='S:\services\memory-engine';port=7020},
    @{slug='pipecat';      name='pipecat';      dir='S:\services\pipecat';      port=7030},
    @{slug='openclaw';     name='openclaw';     dir='S:\services\openclaw';     port=7040},
    @{slug='eva-os';       name='eva-os';       dir='S:\services\eva-os';       port=7050}
)

foreach ($s in $services) {
    $run = @"
param([switch]`$Reload)
. "S:\scripts\lib\sonia-stack.ps1"
`$servicePid = Start-SoniaService -Name "$($s.name)" -ServiceDir "$($s.dir)" -Port $($s.port)
Write-Host "[OK] $($s.name) started (PID `$servicePid, port $($s.port))"
`$servicePid
"@
    Set-Content "S:\scripts\ops\run-$($s.slug).ps1" -Value $run -Encoding UTF8
}

# 3) Write strict start-sonia-stack-v2.ps1 (fails non-zero on any launch error)
$start = @'
param(
    [switch] $SkipHealthCheck,
    [int] $StartupTimeoutSeconds = 90
)
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$svc = @(
    @{name='api-gateway';  script='S:\scripts\ops\run-api-gateway.ps1';  port=7000},
    @{name='model-router'; script='S:\scripts\ops\run-model-router.ps1'; port=7010},
    @{name='memory-engine';script='S:\scripts\ops\run-memory-engine.ps1';port=7020},
    @{name='pipecat';      script='S:\scripts\ops\run-pipecat.ps1';      port=7030},
    @{name='openclaw';     script='S:\scripts\ops\run-openclaw.ps1';     port=7040},
    @{name='eva-os';       script='S:\scripts\ops\run-eva-os.ps1';       port=7050}
)

Write-Host "[SONIA] Starting Sonia Stack..."
Write-Host "[SONIA] Root: S:\"

$failed = $false
foreach ($s in $svc) {
    try {
        Write-Host "[SONIA] Starting $($s.script)..."
        $servicePid = & $s.script
        if (-not $servicePid) { throw "No PID returned" }
    } catch {
        Write-Host "[ERROR] Failed to start $($s.script) : $($_.Exception.Message)"
        $failed = $true
    }
}

if ($failed) { throw "Startup failed for one or more services." }

if (-not $SkipHealthCheck) {
    $deadline = (Get-Date).AddSeconds($StartupTimeoutSeconds)
    do {
        $ok = 0
        foreach ($s in $svc) {
            try {
                $r = Invoke-WebRequest "http://127.0.0.1:$($s.port)/healthz" -TimeoutSec 2
                if ($r.StatusCode -eq 200) { $ok++ }
            } catch {}
        }
        Write-Host ("[SONIA] Health {0}/{1}" -f $ok, $svc.Count)
        if ($ok -eq $svc.Count) { break }
        Start-Sleep -Seconds 1
    } while ((Get-Date) -lt $deadline)

    if ($ok -ne $svc.Count) { throw "Health check failed: $ok/$($svc.Count)" }
}

Write-Host "[OK] Sonia stack startup complete"
exit 0
'@
Set-Content "S:\scripts\ops\start-sonia-stack-v2.ps1" -Value $start -Encoding UTF8

# 4) Ensure no Export-ModuleMember remains
$hits = Get-ChildItem "S:\scripts" -Recurse -Filter *.ps1 | Select-String -Pattern 'Export-ModuleMember' -SimpleMatch
if ($hits) { $hits | ForEach-Object { $_.Path + ":" + $_.LineNumber + " " + $_.Line }; throw "Export-ModuleMember still present." }

Write-Host "Launcher rebuild complete."
