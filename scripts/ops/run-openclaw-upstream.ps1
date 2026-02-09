<#---------------------------------------------------------------------------
run-openclaw-upstream.ps1 (SONIA OpenClaw Upstream Gateway Runner)
Runs vendored OpenClaw upstream Node gateway service.

WINDOWS FIX: Directly invokes node scripts/run-node.mjs with env vars,
bypassing npm/pnpm script wrappers that fail with Unix-style VAR=value syntax.

Default behavior: Starts OpenClaw gateway in dev mode
  - Logs: S:\logs\services\openclaw-upstream.(out|err).log
  - PID : S:\state\pids\openclaw-upstream.pid
  - Env : OPENCLAW_SKIP_CHANNELS=1, CLAWDBOT_SKIP_CHANNELS=1
  - Token: Read from OPENCLAW_GATEWAY_TOKEN env or config file (required)

Usage:
  .\run-openclaw-upstream.ps1                    # Start gateway:dev
  .\run-openclaw-upstream.ps1 -Reset             # Reset dev config
  .\run-openclaw-upstream.ps1 -Token "secret"    # Start with token
  .\run-openclaw-upstream.ps1 -Reinstall         # Force npm install

---------------------------------------------------------------------------#>

[CmdletBinding()]
param(
    [Parameter(Mandatory=$false)]
    [ValidateNotNullOrEmpty()]
    [string]$Root = "S:\",

    [Parameter(Mandatory=$false)]
    [ValidateNotNullOrEmpty()]
    [string]$Script = "gateway",

    [Parameter(Mandatory=$false)]
    [ValidateNotNullOrEmpty()]
    [string]$DevMode = "dev",

    [Parameter(Mandatory=$false)]
    [string]$Token = "",

    [Parameter(Mandatory=$false)]
    [switch]$Reset,

    [Parameter(Mandatory=$false)]
    [switch]$Reinstall,

    [Parameter(Mandatory=$false)]
    [switch]$Verbose
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Write-Log {
    param([string]$Message, [switch]$IsError)
    $prefix = if ($IsError) { "[ERROR]" } else { "[openclaw]" }
    Write-Host "$prefix $Message" -ForegroundColor $(if ($IsError) { "Red" } else { "Gray" })
}

function Ensure-Dir { param([string]$Path) if (-not (Test-Path -LiteralPath $Path)) { New-Item -ItemType Directory -Path $Path -Force | Out-Null } }
function Normalize-Root { param([string]$Path) if ($Path -and -not $Path.EndsWith("\")) { return "$Path\" } return $Path }

$Root = Normalize-Root $Root
$driveLetter = $Root.Substring(0,1)
if (-not (Get-PSDrive -Name $driveLetter -ErrorAction SilentlyContinue)) {
    Write-Log "Drive '$($driveLetter):' does not exist. Update -Root parameter." -IsError
    exit 1
}

# Create required directories
Ensure-Dir (Join-Path $Root "logs\services")
Ensure-Dir (Join-Path $Root "state\pids")
Ensure-Dir (Join-Path $Root "cache\npm")
Ensure-Dir (Join-Path $Root "cache\node-gyp")
Ensure-Dir (Join-Path $Root "cache\pnpm-store")

$PidFile = Join-Path $Root "state\pids\openclaw-upstream.pid"
$OutLog  = Join-Path $Root "logs\services\openclaw-upstream.out.log"
$ErrLog  = Join-Path $Root "logs\services\openclaw-upstream.err.log"

# Validate no existing process
if (Test-Path -LiteralPath $PidFile) {
    $oldPid = (Get-Content -LiteralPath $PidFile -ErrorAction SilentlyContinue | Select-Object -First 1).Trim()
    if ($oldPid -and ($oldPid -as [int])) {
        $oldId = [int]$oldPid
        try {
            $p = Get-Process -Id $oldId -ErrorAction Stop
            Write-Log "Process already running (PID $oldId). Stop it first or delete stale PID file." -IsError
            exit 1
        } catch {
            Remove-Item -LiteralPath $PidFile -Force -ErrorAction SilentlyContinue
        }
    }
}

# Locate upstream root
$CurrentFile = Join-Path $Root "integrations\openclaw\upstream\CURRENT.txt"
if (-not (Test-Path -LiteralPath $CurrentFile)) {
    Write-Log "Missing: $CurrentFile. Import upstream ZIP first." -IsError
    exit 1
}
$UpstreamRoot = (Get-Content -LiteralPath $CurrentFile -ErrorAction Stop | Select-Object -First 1).Trim()
if (-not (Test-Path -LiteralPath $UpstreamRoot)) {
    Write-Log "Upstream root not found: $UpstreamRoot" -IsError
    exit 1
}

$PkgJson = Join-Path $UpstreamRoot "package.json"
if (-not (Test-Path -LiteralPath $PkgJson)) {
    Write-Log "package.json not found at: $UpstreamRoot" -IsError
    exit 1
}

# Validate Node is available
$nodeCmd = Get-Command node.exe -ErrorAction SilentlyContinue
if (-not $nodeCmd -or $nodeCmd.CommandType -ne "Application") {
    Write-Log "node.exe not found on PATH." -IsError
    exit 1
}

# Set cache directories to avoid drift outside S:\
$env:npm_config_cache      = Join-Path $Root "cache\npm"
$env:npm_config_devdir     = Join-Path $Root "cache\node-gyp"
$env:PNPM_STORE_PATH       = Join-Path $Root "cache\pnpm-store"
$env:PNPM_HOME             = Join-Path $Root "cache\pnpm-store"

# Environment variables required by gateway
$env:OPENCLAW_SKIP_CHANNELS = "1"
$env:CLAWDBOT_SKIP_CHANNELS = "1"

if ($Token) {
    $env:OPENCLAW_GATEWAY_TOKEN = $Token
}

# Build npm install command (use pnpm if available, else npm.cmd)
$npmCmd = Get-Command npm.cmd -ErrorAction SilentlyContinue
if ($npmCmd -and $npmCmd.CommandType -eq "Application") {
    $NpmPath = $npmCmd.Source
} else {
    Write-Log "npm.cmd not found. Trying npm..." -IsError
    $npmAlt = Get-Command npm -ErrorAction SilentlyContinue
    if (-not $npmAlt) {
        Write-Log "Neither npm.cmd nor npm found on PATH." -IsError
        exit 1
    }
    $NpmPath = $npmAlt.Source
}

Write-Host ""
Write-Host "=== OpenClaw Upstream Gateway (Sonia) ===" -ForegroundColor Cyan
Write-Host "Root:     $UpstreamRoot"
Write-Host "Script:   $Script"
Write-Host "Mode:     $DevMode"
Write-Host "npm:      $NpmPath"
Write-Host "Logs:     $OutLog"
Write-Host "          $ErrLog"
Write-Host "Token:    $(if ($env:OPENCLAW_GATEWAY_TOKEN) { "[SET]" } else { "[NOT SET - will fail]" })"
Write-Host ""

# Check and install deps
$lockPnpm = Join-Path $UpstreamRoot "pnpm-lock.yaml"
$lockNpm  = Join-Path $UpstreamRoot "package-lock.json"
$nodeMods = Join-Path $UpstreamRoot "node_modules"

if ($Reinstall) {
    if (Test-Path -LiteralPath $nodeMods) {
        Write-Host "Removing node_modules for clean install..."
        Remove-Item -LiteralPath $nodeMods -Recurse -Force
    }
}

$needInstall = (-not (Test-Path -LiteralPath $nodeMods))

if ($needInstall) {
    Write-Host "Installing dependencies..."
    Push-Location $UpstreamRoot
    try {
        if (Test-Path -LiteralPath $lockPnpm) {
            $pnpmCmd = Get-Command pnpm -ErrorAction SilentlyContinue
            if ($pnpmCmd) {
                & pnpm install --frozen-lockfile
            } else {
                & $NpmPath exec pnpm install --frozen-lockfile
            }
        } else {
            & $NpmPath ci
        }
        if ($LASTEXITCODE -ne 0) {
            Write-Log "Failed to install dependencies (exit=$LASTEXITCODE)" -IsError
            exit $LASTEXITCODE
        }
    } finally {
        Pop-Location
    }
} else {
    Write-Host "node_modules exists; skipping install (use -Reinstall to force)."
}

Write-Host ""
Write-Host "Starting gateway..." -ForegroundColor Green

# Prepare log files
"--- started $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss zzz') ---" | Out-File -LiteralPath $OutLog -Encoding UTF8 -Append
"--- started $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss zzz') ---" | Out-File -LiteralPath $ErrLog -Encoding UTF8 -Append

# Build node arguments
# Pattern: node scripts/run-node.mjs --dev gateway [--reset]
$nodeArgs = @("scripts/run-node.mjs", "--$DevMode", $Script)
if ($Reset) {
    $nodeArgs += "--reset"
}

# Start process
$proc = Start-Process -FilePath (Get-Command node.exe).Source `
  -ArgumentList $nodeArgs `
  -WorkingDirectory $UpstreamRoot `
  -RedirectStandardOutput $OutLog `
  -RedirectStandardError $ErrLog `
  -NoNewWindow `
  -PassThru `
  -EnvironmentVariables @{
      OPENCLAW_SKIP_CHANNELS = "1"
      CLAWDBOT_SKIP_CHANNELS = "1"
      OPENCLAW_GATEWAY_TOKEN = $env:OPENCLAW_GATEWAY_TOKEN
  }

Set-Content -LiteralPath $PidFile -Value $proc.Id -Encoding ASCII -NoNewline

# Give process time to start
Start-Sleep -Milliseconds 800

# Check if process crashed immediately
if ($proc.HasExited) {
    Remove-Item -LiteralPath $PidFile -Force -ErrorAction SilentlyContinue
    Write-Log "Process exited immediately (exit=$($proc.ExitCode))" -IsError
    Write-Host ""
    Write-Host "This usually means:"
    Write-Host "  - Missing OPENCLAW_GATEWAY_TOKEN (set it before running)"
    Write-Host "  - Build failure during tsdown compilation"
    Write-Host "  - Missing dependencies"
    Write-Host ""
    Write-Host "Check logs:"
    Write-Host "  tail -f `"$OutLog`""
    Write-Host "  tail -f `"$ErrLog`""
    Write-Host ""
    Get-Content -LiteralPath $ErrLog -Tail 20 2>/dev/null | Write-Host
    exit $proc.ExitCode
}

Write-Host "PID: $($proc.Id)"
Write-Host "PID file: $PidFile"
Write-Host ""
Write-Host "Gateway is running. Tail logs:"
Write-Host "  Get-Content -Wait -Tail 50 `"$OutLog`""
Write-Host "  Get-Content -Wait -Tail 50 `"$ErrLog`""
Write-Host ""
Write-Host "Stop with:"
Write-Host "  .\stop-openclaw-upstream.ps1"
