Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ts = Get-Date -Format "yyyyMMdd-HHmmss"
$evidenceDir = "S:\artifacts\phase3\evidence"
New-Item -ItemType Directory -Path $evidenceDir -Force | Out-Null
$evidenceFile = Join-Path $evidenceDir "PREREQUISITES_COMPLETED_$ts.txt"

function Resolve-PythonCmd {
    if (Get-Command python -ErrorAction SilentlyContinue) { 
        return @("python") 
    }

    if (Get-Command py -ErrorAction SilentlyContinue) {
        foreach ($v in @("-3.11", "-3.10")) {
            try {
                & py $v -c "import sys; raise SystemExit(0 if sys.version_info[:2] >= (3,10) else 1)" 2>$null
                if ($LASTEXITCODE -eq 0) { 
                    return @("py", $v) 
                }
            } 
            catch { }
        }
    }

    return $null
}

function Invoke-Py([string[]]$cmd, [string[]]$args) {
    $prefix = @()
    if ($cmd.Count -gt 1) { 
        $prefix = $cmd[1..($cmd.Count - 1)] 
    }
    & $cmd[0] @prefix @args
}

Start-Transcript -Path $evidenceFile -Force | Out-Null

try {
    Write-Host "=== Phase 3 Prerequisite Check ===" -ForegroundColor Cyan

    $pyCmd = Resolve-PythonCmd
    if ($null -eq $pyCmd) {
        Write-Host "ERROR: No Python 3.10+ found" -ForegroundColor Red
        Write-Host "Install Python 3.10+ from python.org with PATH enabled, then rerun." -ForegroundColor Red
        exit 1
    }

    $ver = (Invoke-Py $pyCmd @("-c", "import sys; print('.'.join(map(str, sys.version_info[:3])))")).Trim()
    Write-Host "Python version check: $ver" -ForegroundColor Green
    
    if ([version]$ver -lt [version]"3.10.0") {
        Write-Host "ERROR: Python version $ver is below 3.10.0" -ForegroundColor Red
        exit 1
    }
    Write-Host "Python OK: $ver" -ForegroundColor Green

    $venvPath = "S:\.venv-phase3"
    if (-not (Test-Path "$venvPath\Scripts\python.exe")) {
        Write-Host "Creating venv: $venvPath" -ForegroundColor Yellow
        Invoke-Py $pyCmd @("-m", "venv", $venvPath) | Out-Null
    }

    $venvPy = "$venvPath\Scripts\python.exe"
    if (-not (Test-Path $venvPy)) { 
        Write-Host "ERROR: Venv python missing: $venvPy" -ForegroundColor Red
        exit 1 
    }

    Write-Host "Upgrading pip..." -ForegroundColor Yellow
    & $venvPy -m pip install --upgrade pip setuptools wheel -q

    $lockFiles = Get-ChildItem "S:\services" -Recurse -File -Include "requirements.lock", "requirements.txt" |
        Sort-Object FullName -Unique

    if (-not $lockFiles -or $lockFiles.Count -eq 0) {
        Write-Host "ERROR: No requirements.lock/requirements.txt found under S:\services" -ForegroundColor Red
        exit 1
    }

    Write-Host "Installing dependencies..." -ForegroundColor Yellow
    foreach ($f in $lockFiles) {
        Write-Host "  From: $($f.FullName)" -ForegroundColor Gray
        & $venvPy -m pip install -r $f.FullName -q
    }

    Write-Host "Verifying imports..." -ForegroundColor Yellow
    & $venvPy -c "import fastapi, uvicorn; print('imports_ok')" | Out-Null

    Write-Host "Running strict preflight validator..." -ForegroundColor Yellow
    $preflight = "S:\scripts\testing\phase3-preflight.ps1"
    if (-not (Test-Path $preflight)) { 
        Write-Host "ERROR: Missing preflight script: $preflight" -ForegroundColor Red
        exit 1 
    }

    & $preflight
    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERROR: Preflight failed" -ForegroundColor Red
        exit 1
    }

    Write-Host "PREREQUISITES: PASS" -ForegroundColor Green
    Write-Host "Evidence: $evidenceFile" -ForegroundColor Green
    exit 0
}
catch {
    Write-Host "ERROR: $_" -ForegroundColor Red
    exit 1
}
finally {
    Stop-Transcript | Out-Null
}
