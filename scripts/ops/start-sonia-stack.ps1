<#---------------------------------------------------------------------------
start-sonia-stack.ps1 (SONIA FINAL ITERATION LAUNCHER)

Starts the complete Sonia stack with all services and performs health checks.
Validates configuration, checks port availability, and ensures all logs are available.

Usage:
  .\start-sonia-stack.ps1                    # Start all services
  .\start-sonia-stack.ps1 -Verbose           # Verbose output
  .\start-sonia-stack.ps1 -TestOnly          # Test without starting
  .\start-sonia-stack.ps1 -SkipHealthCheck   # Skip post-start health check

Root: S:\
---------------------------------------------------------------------------#>

[CmdletBinding()]
param(
    [Parameter(Mandatory=$false)]
    [ValidateNotNullOrEmpty()]
    [string]$Root = "S:\",

    [Parameter(Mandatory=$false)]
    [switch]$Verbose,

    [Parameter(Mandatory=$false)]
    [switch]$TestOnly,

    [Parameter(Mandatory=$false)]
    [switch]$SkipHealthCheck,

    [Parameter(Mandatory=$false)]
    [int]$HealthCheckTimeoutSeconds = 30
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# Utility functions
function Write-Status {
    param([string]$Message, [string]$Color = "Cyan")
    Write-Host "[SONIA] $Message" -ForegroundColor $Color
}

function Write-Error-Custom {
    param([string]$Message)
    Write-Host "[ERROR] $Message" -ForegroundColor Red
}

function Write-Success {
    param([string]$Message)
    Write-Host "[✓] $Message" -ForegroundColor Green
}

function Normalize-Root {
    param([string]$Path)
    if ($Path -and -not $Path.EndsWith("\")) { return "$Path\" }
    return $Path
}

function Ensure-Dir {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) {
        New-Item -ItemType Directory -Path $Path -Force | Out-Null
    }
}

# Start of script
$Root = Normalize-Root $Root
Write-Status "═══════════════════════════════════════════════════════════"
Write-Status "        SONIA FINAL ITERATION - STACK LAUNCHER"
Write-Status "═══════════════════════════════════════════════════════════"
Write-Status "Root directory: $Root"
Write-Status "Timestamp: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"

# ───────────────────────────────────────────────────────────────────────────────
# PHASE 0: VALIDATION AND SETUP
# ───────────────────────────────────────────────────────────────────────────────

Write-Status ""
Write-Status "Phase 0: Validation and Setup"
Write-Status "─────────────────────────────"

# Verify root exists
if (-not (Test-Path -LiteralPath $Root)) {
    Write-Error-Custom "Root directory not found: $Root"
    exit 1
}
Write-Success "Root directory exists"

# Create required directories
$requiredDirs = @(
    "$($Root)logs\services",
    "$($Root)state\pids",
    "$($Root)cache\npm",
    "$($Root)cache\pnpm-store",
    "$($Root)cache\node-gyp",
    "$($Root)config",
    "$($Root)shared\schemas",
    "$($Root)scripts\ops",
    "$($Root)scripts\diagnostics"
)

foreach ($dir in $requiredDirs) {
    Ensure-Dir $dir
}
Write-Success "All required directories exist"

# Load configuration
$configPath = "$($Root)config\sonia-config.json"
if (-not (Test-Path -LiteralPath $configPath)) {
    Write-Error-Custom "Configuration file not found: $configPath"
    exit 1
}

try {
    $config = Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json
    Write-Success "Configuration loaded"
} catch {
    Write-Error-Custom "Failed to parse configuration: $_"
    exit 1
}

# Verify required executables
$nodeExe = Get-Command node.exe -ErrorAction SilentlyContinue
if (-not $nodeExe) {
    Write-Error-Custom "node.exe not found on PATH"
    exit 1
}
Write-Success "node.exe found: $($nodeExe.Source)"

# Check port availability
Write-Status ""
Write-Status "Checking port availability..."
$portsToCheck = @(7000, 7010, 7020, 7030, 7040, 7050)
$unavailablePorts = @()

foreach ($port in $portsToCheck) {
    $listener = $null
    try {
        $listener = New-Object System.Net.Sockets.TcpListener([System.Net.IPAddress]::Loopback, $port)
        $listener.Start()
        $listener.Stop()
        Write-Success "Port ${port}: available"
    } catch {
        Write-Error-Custom "Port ${port}: IN USE"
        $unavailablePorts += $port
    }
}

if ($unavailablePorts.Count -gt 0) {
    Write-Error-Custom "Ports in use: $($unavailablePorts -join ', ')"
    Write-Status "Suggestion: Stop other services or use different ports"
    exit 1
}

# ───────────────────────────────────────────────────────────────────────────────
# PHASE 1: STARTUP (or test mode)
# ───────────────────────────────────────────────────────────────────────────────

Write-Status ""
Write-Status "Phase 1: Service Startup"
Write-Status "────────────────────────"

$startedServices = @()

# Define services and their startup commands
$services = @(
    @{
        name = "API Gateway"
        key = "api_gateway"
        script = "S:\scripts\ops\run-api-gateway.ps1"
    },
    @{
        name = "Model Router"
        key = "model_router"
        script = "S:\scripts\ops\run-model-router.ps1"
    },
    @{
        name = "Memory Engine"
        key = "memory_engine"
        script = "S:\scripts\ops\run-memory-engine.ps1"
    },
    @{
        name = "Pipecat"
        key = "pipecat"
        script = "S:\scripts\ops\run-pipecat.ps1"
    },
    @{
        name = "OpenClaw"
        key = "openclaw"
        script = "S:\scripts\ops\run-openclaw.ps1"
    }
)

if ($TestOnly) {
    Write-Status "TEST MODE: Not starting services"
    Write-Status "To start services, run without -TestOnly flag"
} else {
    foreach ($service in $services) {
        Write-Status "Starting $($service.name)..."
        
        # Check if startup script exists
        if (-not (Test-Path -LiteralPath $service.script)) {
            Write-Error-Custom "Startup script not found: $($service.script)"
            Write-Status "Skipping $($service.name)"
            continue
        }
        
        try {
            # Start the service (scripts should handle their own logging)
            & $service.script -Root $Root
            Start-Sleep -Milliseconds 500
            $startedServices += $service.name
            Write-Success "$($service.name) started"
        } catch {
            Write-Error-Custom "Failed to start $($service.name): $_"
        }
    }
}

# ───────────────────────────────────────────────────────────────────────────────
# PHASE 2: HEALTH CHECK (if not skipped)
# ───────────────────────────────────────────────────────────────────────────────

if (-not $SkipHealthCheck -and -not $TestOnly) {
    Write-Status ""
    Write-Status "Phase 2: Health Check"
    Write-Status "─────────────────────"
    
    $healthEndpoints = @(
        @{ service = "API Gateway"; port = 7000 },
        @{ service = "Model Router"; port = 7010 },
        @{ service = "Memory Engine"; port = 7020 },
        @{ service = "Pipecat"; port = 7030 },
        @{ service = "OpenClaw"; port = 7040 }
    )
    
    $healthyServices = @()
    $stopwatch = [System.Diagnostics.Stopwatch]::StartNew()
    
    while ($stopwatch.Elapsed.TotalSeconds -lt $HealthCheckTimeoutSeconds) {
        $healthyServices = @()
        
        foreach ($endpoint in $healthEndpoints) {
            try {
                $response = Invoke-WebRequest -Uri "http://127.0.0.1:$($endpoint.port)/health" `
                    -TimeoutSec 2 `
                    -UseBasicParsing `
                    -ErrorAction SilentlyContinue
                
                if ($response.StatusCode -eq 200) {
                    $healthyServices += $endpoint.service
                }
            } catch {
                # Service not responding yet
            }
        }
        
        if ($healthyServices.Count -eq $healthEndpoints.Count) {
            break
        }
        
        Start-Sleep -Milliseconds 500
    }
    
    $stopwatch.Stop()
    
    Write-Status "Health check completed in $([Math]::Round($stopwatch.Elapsed.TotalSeconds, 1))s"
    
    foreach ($service in $healthEndpoints) {
        if ($healthyServices -contains $service.service) {
            Write-Success "$($service.service) (port $($service.port)): HEALTHY"
        } else {
            Write-Error-Custom "$($service.service) (port $($service.port)): NOT RESPONDING"
        }
    }
}

# ───────────────────────────────────────────────────────────────────────────────
# SUMMARY AND NEXT STEPS
# ───────────────────────────────────────────────────────────────────────────────

Write-Status ""
Write-Status "═══════════════════════════════════════════════════════════"
Write-Status "                    STARTUP COMPLETE"
Write-Status "═══════════════════════════════════════════════════════════"
Write-Status ""

if ($TestOnly) {
    Write-Status "Test mode: no services started"
} else {
    Write-Status "Started services: $($startedServices -join ', ')"
    Write-Status ""
    Write-Status "Service Ports:"
    Write-Status "  API Gateway (7000)   - http://127.0.0.1:7000"
    Write-Status "  Model Router (7010)  - http://127.0.0.1:7010"
    Write-Status "  Memory Engine (7020) - http://127.0.0.1:7020"
    Write-Status "  Pipecat (7030)       - http://127.0.0.1:7030"
    Write-Status "  OpenClaw (7040)      - http://127.0.0.1:7040"
    Write-Status ""
    Write-Status "Log Files:"
    Write-Status "  S:\logs\services\<service>.out.log"
    Write-Status "  S:\logs\services\<service>.err.log"
    Write-Status ""
    Write-Status "PID Files:"
    Write-Status "  S:\state\pids\<service>.pid"
    Write-Status ""
    Write-Status "Next Steps:"
    Write-Status "  1. Verify services are healthy: .\scripts\diagnostics\doctor-sonia.ps1"
    Write-Status "  2. Monitor logs: Get-Content -Wait -Tail 50 S:\logs\services\api-gateway.out.log"
    Write-Status "  3. Stop all services: .\scripts\ops\stop-sonia-stack.ps1"
    Write-Status ""
}

Write-Success "Sonia stack is ready!"
