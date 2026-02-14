<#
.SYNOPSIS
Start the complete Sonia stack (v3.0)

.DESCRIPTION
Starts all Sonia services in order with pre-flight checks:
  0. Pre-flight: Python env, Ollama, models, ports, GPU VRAM
  1. API Gateway (7000)
  2. Model Router (7010)
  3. Memory Engine (7020)
  4. Pipecat (7030)
  5. OpenClaw (7040)
  6. EVA-OS (7050) - optional

Performs health checks after startup and displays logs.

.PARAMETER Root
Sonia root directory. Defaults to S:\

.PARAMETER Reload
Enable auto-reload for development (passes -Reload to each service)

.PARAMETER SkipHealthCheck
Skip health checks after startup

.PARAMETER SkipPreflight
Skip pre-flight environment checks

.PARAMETER TestOnly
Test configuration without starting services

.PARAMETER LaunchUI
Also launch the Electron UI after services are healthy

.EXAMPLE
.\start-sonia-stack.ps1
.\start-sonia-stack.ps1 -Reload
.\start-sonia-stack.ps1 -SkipHealthCheck
.\start-sonia-stack.ps1 -LaunchUI
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory=$false)]
    [string]$Root = "S:\",

    [Parameter(Mandatory=$false)]
    [switch]$Reload,

    [Parameter(Mandatory=$false)]
    [switch]$SkipHealthCheck,

    [Parameter(Mandatory=$false)]
    [switch]$SkipPreflight,

    [Parameter(Mandatory=$false)]
    [switch]$TestOnly,

    [Parameter(Mandatory=$false)]
    [switch]$LaunchUI,

    [Parameter(Mandatory=$false)]
    [int]$HealthCheckTimeoutSeconds = 30
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# Import library
. (Join-Path $Root "scripts\lib\sonia-stack.ps1")

# --------------------------------------------------------------───────────────────
# Setup
# --------------------------------------------------------------───────────────────

$root = Get-SoniaRoot $Root
Write-Host ""
Write-Host "+=========================================================+" -ForegroundColor Cyan
Write-Host "|           SONIA STACK LAUNCHER v3.0                     |" -ForegroundColor Cyan
Write-Host "+=========================================================+" -ForegroundColor Cyan
Write-Host ""
Write-Host "Root: $root" -ForegroundColor Gray
Write-Host "Reload: $(if ($Reload) { 'ENABLED' } else { 'disabled' })" -ForegroundColor Gray
Write-Host "Health checks: $(if ($SkipHealthCheck) { 'disabled' } else { 'ENABLED' })" -ForegroundColor Gray
Write-Host ""

# Validate root
if (-not (Test-Path -LiteralPath $root)) {
    Write-Host "[FAIL] Root directory not found: $root" -ForegroundColor Red
    exit 1
}

# Create required directories
Ensure-Dir (Join-Path $root "state\pids") | Out-Null
Ensure-Dir (Join-Path $root "logs\services") | Out-Null

# Define services
$services = @(
    @{ Name = "API Gateway"; Script = "run-api-gateway.ps1"; Port = 7000 },
    @{ Name = "Model Router"; Script = "run-model-router.ps1"; Port = 7010 },
    @{ Name = "Memory Engine"; Script = "run-memory-engine.ps1"; Port = 7020 },
    @{ Name = "Pipecat"; Script = "run-pipecat.ps1"; Port = 7030 },
    @{ Name = "OpenClaw"; Script = "run-openclaw.ps1"; Port = 7040 }
)

# Check if EVA-OS exists
$evaOsDir = Join-Path $root "services\eva-os"
if (Test-Path -LiteralPath $evaOsDir) {
    $services += @{ Name = "EVA-OS"; Script = "run-eva-os.ps1"; Port = 7050 }
}

# Check if Vision Capture exists
$visionDir = Join-Path $root "services\vision-capture"
if (Test-Path -LiteralPath $visionDir) {
    $services += @{ Name = "Vision Capture"; Script = "run-vision-capture.ps1"; Port = 7060 }
}

# Check if Perception exists
$perceptionDir = Join-Path $root "services\perception"
if (Test-Path -LiteralPath $perceptionDir) {
    $services += @{ Name = "Perception"; Script = "run-perception.ps1"; Port = 7070 }
}

# Check if MCP Server exists
$mcpDir = Join-Path $root "services\mcp-server"
if (Test-Path -LiteralPath $mcpDir) {
    $services += @{ Name = "MCP Server"; Script = "run-mcp-server.ps1"; Port = 8080 }
}

# --------------------------------------------------------------───────────────────
# Validation Phase
# --------------------------------------------------------------───────────────────

Write-Host "Phase 0: Validation" -ForegroundColor Cyan
Write-Host "--------------------------------------------------------------"

$allValid = $true
foreach ($svc in $services) {
    $scriptPath = Join-Path $root "scripts\ops\$($svc.Script)"
    if (-not (Test-Path -LiteralPath $scriptPath)) {
        Write-Host "[FAIL] Script not found: $($svc.Script)" -ForegroundColor Red
        $allValid = $false
    } else {
        Write-Host "[OK] $($svc.Name) script exists" -ForegroundColor Green
    }
}

if (-not $allValid) {
    Write-Host ""
    Write-Host "[FAIL] Validation failed" -ForegroundColor Red
    exit 1
}

Write-Host "[OK] All startup scripts found" -ForegroundColor Green
Write-Host ""

# --------------------------------------------------------------───────────────────
# Pre-flight Checks
# --------------------------------------------------------------───────────────────

if (-not $SkipPreflight) {
    Write-Host "Phase 0b: Pre-flight Checks" -ForegroundColor Cyan
    Write-Host "--------------------------------------------------------------"

    $preflightOk = $true
    $warnings = @()

    # 1. Python environment
    $pythonExe = Join-Path $root "envs\sonia-core\python.exe"
    if (Test-Path -LiteralPath $pythonExe) {
        $pyVer = & $pythonExe --version 2>&1
        Write-Host "[OK] Python: $pyVer" -ForegroundColor Green
    } else {
        Write-Host "[FAIL] Python env not found: $pythonExe" -ForegroundColor Red
        $preflightOk = $false
    }

    # 2. Ollama running
    $ollamaUp = $false
    try {
        $ollamaResp = Invoke-WebRequest -Uri "http://127.0.0.1:11434/api/tags" -TimeoutSec 3 -UseBasicParsing -ErrorAction Stop
        if ($ollamaResp.StatusCode -eq 200) {
            $ollamaUp = $true
            $ollamaData = $ollamaResp.Content | ConvertFrom-Json
            $modelCount = 0
            if ($ollamaData.models) { $modelCount = $ollamaData.models.Count }
            Write-Host "[OK] Ollama running ($modelCount models loaded)" -ForegroundColor Green
        }
    } catch {
        Write-Host "[WARN] Ollama not reachable at :11434 (model inference will fail)" -ForegroundColor Yellow
        $warnings += "Ollama not running"
    }

    # 3. Required models in Ollama (check if ollama is up)
    if ($ollamaUp) {
        $configPath = Join-Path $root "config\sonia-config.json"
        if (Test-Path -LiteralPath $configPath) {
            try {
                $config = Get-Content $configPath -Raw | ConvertFrom-Json
                $requiredModels = @()
                # Check for configured model names
                if ($config.model_router -and $config.model_router.default_model) {
                    $requiredModels += $config.model_router.default_model
                }
                if ($config.model_router -and $config.model_router.models) {
                    foreach ($m in $config.model_router.models.PSObject.Properties) {
                        if ($m.Value.ollama_model) {
                            $requiredModels += $m.Value.ollama_model
                        }
                    }
                }
                $requiredModels = $requiredModels | Select-Object -Unique
                if ($requiredModels.Count -gt 0) {
                    $ollamaModels = @()
                    if ($ollamaData.models) {
                        $ollamaModels = $ollamaData.models | ForEach-Object { $_.name }
                    }
                    foreach ($reqModel in $requiredModels) {
                        $found = $ollamaModels | Where-Object { $_ -like "$reqModel*" }
                        if ($found) {
                            Write-Host "[OK] Model available: $reqModel" -ForegroundColor Green
                        } else {
                            Write-Host "[WARN] Model not found in Ollama: $reqModel" -ForegroundColor Yellow
                            $warnings += "Missing model: $reqModel"
                        }
                    }
                }
            } catch {
                # Config parse failure is non-fatal for preflight
            }
        }
    }

    # 4. Port conflict detection
    $portConflicts = @()
    foreach ($svc in $services) {
        $portInUse = $false
        try {
            $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, $svc.Port)
            $listener.Start()
            $listener.Stop()
        } catch {
            $portInUse = $true
        }
        if ($portInUse) {
            # Check if it's already a Sonia service
            $isSonia = $false
            try {
                $resp = Invoke-WebRequest -Uri "http://127.0.0.1:$($svc.Port)/healthz" -TimeoutSec 2 -UseBasicParsing -ErrorAction Stop
                $healthData = $resp.Content | ConvertFrom-Json
                if ($healthData.service) { $isSonia = $true }
            } catch {}

            if ($isSonia) {
                Write-Host "[OK] Port $($svc.Port) ($($svc.Name)) -- already running" -ForegroundColor Green
            } else {
                Write-Host "[WARN] Port $($svc.Port) in use by non-Sonia process" -ForegroundColor Yellow
                $portConflicts += $svc.Port
                $warnings += "Port conflict: $($svc.Port)"
            }
        } else {
            Write-Host "[OK] Port $($svc.Port) ($($svc.Name)) -- available" -ForegroundColor Green
        }
    }

    # 5. GPU VRAM check
    try {
        $nvSmi = nvidia-smi --query-gpu=name,memory.total,memory.used,memory.free,utilization.gpu --format=csv,noheader,nounits 2>&1
        if ($LASTEXITCODE -eq 0) {
            $gpuParts = ($nvSmi -split ",") | ForEach-Object { $_.Trim() }
            if ($gpuParts.Count -ge 5) {
                $gpuName = $gpuParts[0]
                $totalMB = [int]$gpuParts[1]
                $usedMB = [int]$gpuParts[2]
                $freeMB = [int]$gpuParts[3]
                $utilPct = [int]$gpuParts[4]
                $totalGB = [math]::Round($totalMB / 1024, 1)
                $freeGB = [math]::Round($freeMB / 1024, 1)
                Write-Host "[OK] GPU: $gpuName ($($freeGB)GB free / $($totalGB)GB total, ${utilPct}% util)" -ForegroundColor Green
                if ($freeGB -lt 4) {
                    Write-Host "[WARN] Low GPU VRAM -- less than 4GB free" -ForegroundColor Yellow
                    $warnings += "Low VRAM: ${freeGB}GB free"
                }
            }
        }
    } catch {
        Write-Host "[WARN] nvidia-smi not available (no GPU or driver issue)" -ForegroundColor Yellow
        $warnings += "No GPU detected"
    }

    Write-Host ""
    if ($warnings.Count -gt 0) {
        Write-Host "Pre-flight warnings ($($warnings.Count)):" -ForegroundColor Yellow
        foreach ($w in $warnings) {
            Write-Host "  - $w" -ForegroundColor Yellow
        }
        Write-Host ""
    }

    if (-not $preflightOk) {
        Write-Host "[FAIL] Pre-flight checks failed. Fix issues above before starting." -ForegroundColor Red
        exit 1
    }
}

if ($TestOnly) {
    Write-Host "Test mode: configuration valid, not starting services" -ForegroundColor Yellow
    exit 0
}

# --------------------------------------------------------------───────────────────
# Startup Phase
# --------------------------------------------------------------───────────────────

Write-Host "Phase 1: Startup" -ForegroundColor Cyan
Write-Host "--------------------------------------------------------------"

$startedServices = @()
$failedServices = @()

foreach ($svc in $services) {
    $scriptPath = Join-Path $root "scripts\ops\$($svc.Script)"
    
    try {
        Write-Host "Starting $($svc.Name)..." -ForegroundColor Gray
        
        # Runner scripts are self-contained; invoke directly
        & $scriptPath
        $startedServices += $svc
        Start-Sleep -Milliseconds 500
    }
    catch {
        Write-Host "[FAIL] Failed to start $($svc.Name): $_" -ForegroundColor Red
        $failedServices += $svc
    }
}

Write-Host ""

# --------------------------------------------------------------───────────────────
# Health Check Phase
# --------------------------------------------------------------───────────────────

if (-not $SkipHealthCheck) {
    Write-Host "Phase 2: Health Check" -ForegroundColor Cyan
    Write-Host "--------------------------------------------------------------"
    Write-Host "Waiting up to ${HealthCheckTimeoutSeconds}s for services to be ready..." -ForegroundColor Gray
    Write-Host ""
    
    $stopwatch = [System.Diagnostics.Stopwatch]::StartNew()
    $healthyCount = 0
    
    foreach ($svc in $startedServices) {
        $isHealthy = $false
        $elapsed = 0
        
        while ($stopwatch.Elapsed.TotalSeconds -lt $HealthCheckTimeoutSeconds) {
            if (Test-SoniaServiceHealth -Port $svc.Port) {
                $isHealthy = $true
                break
            }
            Start-Sleep -Milliseconds 200
        }
        
        $elapsed = [Math]::Round($stopwatch.Elapsed.TotalSeconds, 1)
        
        if ($isHealthy) {
            Write-Host "[OK] $($svc.Name) (port $($svc.Port))" -ForegroundColor Green
            $healthyCount++
        } else {
            Write-Host "[FAIL] $($svc.Name) (port $($svc.Port)) - not responding" -ForegroundColor Red
        }
    }
    
    Write-Host ""
    Write-Host "Health check completed in ${elapsed}s ($healthyCount/$($startedServices.Count) healthy)" -ForegroundColor Gray
}

# --------------------------------------------------------------───────────────────
# Summary
# --------------------------------------------------------------───────────────────

Write-Host ""
Write-Host "+=========================================================+" -ForegroundColor Cyan
Write-Host "|           STARTUP COMPLETE                              |" -ForegroundColor Cyan
Write-Host "+=========================================================+" -ForegroundColor Cyan
Write-Host ""

if ($failedServices.Count -gt 0) {
    Write-Host "[WARN] Failed services: $($failedServices.Name -join ', ')" -ForegroundColor Yellow
}

Write-Host "Started services: $($startedServices.Name -join ', ')" -ForegroundColor Green
Write-Host ""

Write-Host "Service Endpoints:" -ForegroundColor Cyan
foreach ($svc in $startedServices) {
    Write-Host "  $($svc.Name): http://127.0.0.1:$($svc.Port)" -ForegroundColor Gray
}
Write-Host ""

Write-Host "Log files: $root\logs\services\" -ForegroundColor Gray
Write-Host "PID files: $root\state\pids\" -ForegroundColor Gray
Write-Host ""

Write-Host "Next steps:" -ForegroundColor Cyan
Write-Host "  Check health: iwr http://127.0.0.1:7000/healthz" -ForegroundColor Gray
Write-Host "  Stop all:     .\stop-sonia-stack.ps1" -ForegroundColor Gray
Write-Host "  View logs:    Get-Content $root\logs\services\api-gateway.out.log -Wait -Tail 20" -ForegroundColor Gray
Write-Host "  Launch UI:    npm run electron --prefix $root\ui\sonia-avatar" -ForegroundColor Gray
Write-Host ""

# --------------------------------------------------------------───────────────────
# Optional: Launch UI
# --------------------------------------------------------------───────────────────

if ($LaunchUI) {
    $uiDir = Join-Path $root "ui\sonia-avatar"
    if (Test-Path -LiteralPath (Join-Path $uiDir "dist\index.html")) {
        Write-Host "Launching Sonia UI..." -ForegroundColor Cyan
        $electronExe = Join-Path $uiDir "node_modules\.bin\electron.cmd"
        $mainJs = Join-Path $uiDir "electron\main.js"
        if (Test-Path -LiteralPath $electronExe) {
            Start-Process -FilePath $electronExe -ArgumentList $mainJs -WorkingDirectory $uiDir
            Write-Host "[OK] Electron UI launched" -ForegroundColor Green
        } else {
            Write-Host "[WARN] Electron not found. Run 'npm install' in $uiDir first." -ForegroundColor Yellow
        }
    } else {
        Write-Host "[WARN] UI not built. Run 'npm run build' in $uiDir first." -ForegroundColor Yellow
    }
    Write-Host ""
}
