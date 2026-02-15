<#---------------------------------------------------------------------------
doctor-openclaw-upstream.ps1
Validates prerequisites for running OpenClaw upstream gateway service.

Checks:
  - Upstream repository exists and has package.json
  - Node/npm availability and versions
  - package.json engine requirements
  - Required environment variables/config
  - Port availability (7000-7040 reserved by Sonia)
  - Build artifacts

Prints actionable failure messages and fix commands.

Usage:
  .\doctor-openclaw-upstream.ps1
  .\doctor-openclaw-upstream.ps1 -Verbose
---------------------------------------------------------------------------#>

[CmdletBinding()]
param(
    [Parameter(Mandatory=$false)]
    [ValidateNotNullOrEmpty()]
    [string]$Root = "S:\",

    [Parameter(Mandatory=$false)]
    [switch]$Verbose
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$checks = @(
    @{ name = "Root directory"; category = "setup" }
    @{ name = "CURRENT.txt"; category = "setup" }
    @{ name = "Upstream repository"; category = "setup" }
    @{ name = "Node.exe"; category = "runtime" }
    @{ name = "npm"; category = "runtime" }
    @{ name = "Node version"; category = "version" }
    @{ name = "package.json"; category = "repo" }
    @{ name = "Engine requirements"; category = "version" }
    @{ name = "Build artifacts (dist/)"; category = "build" }
    @{ name = "Sonia port conflicts"; category = "ports" }
    @{ name = "Environment setup"; category = "config" }
)

$passed = @()
$failed = @()
$warned = @()

function Check { param([string]$Name, [scriptblock]$Block)
    Write-Host "  * $Name..." -NoNewline
    try {
        $result = & $Block
        if ($result -eq $true) {
            Write-Host " [OK]" -ForegroundColor Green
            $script:passed += $Name
        } else {
            Write-Host " [FAIL]" -ForegroundColor Red
            $script:failed += @{ name = $Name; detail = $result }
        }
    } catch {
        Write-Host " [FAIL]" -ForegroundColor Red
        $script:failed += @{ name = $Name; detail = $_.Exception.Message }
    }
}

function Warn { param([string]$Name, [string]$Message)
    Write-Host "  [WARN]$Name" -ForegroundColor Yellow
    $script:warned += @{ name = $Name; detail = $Message }
}

function Normalize-Root { param([string]$Path) if ($Path -and -not $Path.EndsWith("\")) { return "$Path\" } return $Path }

$Root = Normalize-Root $Root

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  OpenClaw Upstream Gateway - Diagnostic Check" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

# === SETUP CHECKS ===
Write-Host "Setup" -ForegroundColor Cyan
Check "Root directory exists" {
    if (Test-Path -LiteralPath $Root) { return $true }
    return "Root drive not found: $Root"
}

$CurrentFile = Join-Path $Root "integrations\openclaw\upstream\CURRENT.txt"
Check "CURRENT.txt exists" {
    if (Test-Path -LiteralPath $CurrentFile) { return $true }
    return "Missing: $CurrentFile (import upstream ZIP first)"
}

$UpstreamRoot = ""
if (Test-Path -LiteralPath $CurrentFile) {
    $UpstreamRoot = (Get-Content -LiteralPath $CurrentFile -ErrorAction Stop | Select-Object -First 1).Trim()
}

Check "Upstream repository exists" {
    if ($UpstreamRoot -and (Test-Path -LiteralPath $UpstreamRoot)) { return $true }
    return "Path not found: $UpstreamRoot"
}

# === RUNTIME CHECKS ===
Write-Host ""
Write-Host "Runtime" -ForegroundColor Cyan

$nodePath = ""
Check "Node.exe on PATH" {
    $cmd = Get-Command node.exe -ErrorAction SilentlyContinue
    if ($cmd -and $cmd.CommandType -eq "Application") {
        $script:nodePath = $cmd.Source
        return $true
    }
    return "node.exe not found on PATH"
}

$npmPath = ""
Check "npm on PATH" {
    $cmd = Get-Command npm.cmd -ErrorAction SilentlyContinue
    if ($cmd -and $cmd.CommandType -eq "Application") {
        $script:npmPath = $cmd.Source
        return $true
    }
    $alt = Get-Command npm -ErrorAction SilentlyContinue
    if ($alt) {
        $script:npmPath = $alt.Source
        return $true
    }
    return "npm.cmd or npm not found on PATH"
}

# === VERSION CHECKS ===
Write-Host ""
Write-Host "Versions" -ForegroundColor Cyan

$nodeVersion = ""
Check "Node version" {
    $ver = (& $nodePath --version 2>&1)
    $script:nodeVersion = $ver.Trim()
    return $true
}

$pkgJson = ""
$pkgObj = $null
if ($UpstreamRoot) {
    $pkgJson = Join-Path $UpstreamRoot "package.json"
    if (Test-Path -LiteralPath $pkgJson) {
        $pkgObj = Get-Content -LiteralPath $pkgJson -Raw | ConvertFrom-Json
    }
}

Check "Engine requirement (package.json)" {
    if (-not $pkgObj.engines -or -not $pkgObj.engines.node) {
        return "No engine requirement found (assumed compatible)"
    }
    $required = $pkgObj.engines.node
    Write-Host " (requires: $required)"
    return $true
}

if ($nodeVersion -and $pkgObj.engines.node) {
    $nodeVer = $nodeVersion -replace "^v", ""
    $major = [int]($nodeVer.Split(".")[0])
    $required = $pkgObj.engines.node
    
    $minMajor = 0
    if ($required -match '>=\s*(\d+)') {
        $minMajor = [int]$matches[1]
    } elseif ($required -match '~(\d+)') {
        $minMajor = [int]$matches[1]
    }
    
    if ($major -lt $minMajor -and $minMajor -gt 0) {
        Warn "Node version mismatch" "Installed: $nodeVersion, Required: >=v$minMajor. Upgrade Node.js."
    }
}

# === REPO CHECKS ===
Write-Host ""
Write-Host "Repository" -ForegroundColor Cyan

Check "package.json exists" {
    if ($pkgJson -and (Test-Path -LiteralPath $pkgJson)) { return $true }
    return "Missing: $pkgJson"
}

if ($pkgObj) {
    Check "gateway scripts defined" {
        $hasGateway = $pkgObj.scripts.gateway -or $pkgObj.scripts."gateway:dev"
        if ($hasGateway) { return $true }
        return "No 'gateway' or 'gateway:dev' script in package.json"
    }

    Check "packageManager specified" {
        $pm = $pkgObj.packageManager
        if ($pm) {
            Write-Host " ($pm)"
            return $true
        }
        return "No packageManager field (assumed npm)"
    }
}

# === BUILD CHECKS ===
Write-Host ""
Write-Host "Build" -ForegroundColor Cyan

$distEntry = ""
if ($UpstreamRoot) {
    $distEntry = Join-Path $UpstreamRoot "dist\entry.js"
}

Check "dist/entry.js exists" {
    if ($distEntry -and (Test-Path -LiteralPath $distEntry)) {
        return $true
    }
    return "Missing: $distEntry (run: pnpm build)"
}

# === PORT CHECKS ===
Write-Host ""
Write-Host "Ports (Sonia reserves 7000-7040)" -ForegroundColor Cyan

$soniaPortsInUse = @()
7000..7040 | ForEach-Object {
    $port = $_
    $tcpListener = $null
    try {
        $tcpListener = New-Object System.Net.Sockets.TcpListener([System.Net.IPAddress]::Loopback, $port)
        $tcpListener.Start()
        $tcpListener.Stop()
    } catch {
        $soniaPortsInUse += $port
    }
}

Check "Sonia ports (7000-7040) available" {
    if ($soniaPortsInUse.Count -eq 0) { return $true }
    return "Ports in use: $($soniaPortsInUse -join ', ')"
}

# === CONFIG CHECKS ===
Write-Host ""
Write-Host "Configuration" -ForegroundColor Cyan

$hasToken = $env:OPENCLAW_GATEWAY_TOKEN -or
            (Test-Path -LiteralPath (Join-Path $Root "secrets\openclaw\gateway.token"))

if (-not $hasToken) {
    Warn "OPENCLAW_GATEWAY_TOKEN not set" `
         "Gateway requires authentication token. Set `$env:OPENCLAW_GATEWAY_TOKEN or create: $Root\secrets\openclaw\gateway.token"
}

Check "Cache directories configurable" {
    $cacheRoot = Join-Path $Root "cache"
    if ((Test-Path -LiteralPath $cacheRoot) -or
        ([io.path]::GetDirectoryName($cacheRoot) | Test-Path)) {
        return $true
    }
    return "Cannot create cache directory"
}

# === SUMMARY ===
Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  Diagnostic Summary" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

Write-Host "Passed:  " -NoNewline -ForegroundColor Green
Write-Host "$($passed.Count) checks" -ForegroundColor Green
if ($Verbose) {
    $passed | ForEach-Object { Write-Host "  [OK] $_" }
    Write-Host ""
}

if ($warned.Count -gt 0) {
    Write-Host "Warnings: " -NoNewline -ForegroundColor Yellow
    Write-Host "$($warned.Count) items" -ForegroundColor Yellow
    $warned | ForEach-Object {
        Write-Host "  [WARN]$($_.name)"
        Write-Host "    $($_.detail)" -ForegroundColor DarkYellow
    }
    Write-Host ""
}

if ($failed.Count -gt 0) {
    Write-Host "Failed:  " -NoNewline -ForegroundColor Red
    Write-Host "$($failed.Count) checks" -ForegroundColor Red
    $failed | ForEach-Object {
        Write-Host "  [FAIL] $($_.name)"
        Write-Host "    $($_.detail)" -ForegroundColor DarkRed
    }
    Write-Host ""
    Write-Host "Next steps:" -ForegroundColor Red
    Write-Host "  1. Fix all 'Failed' items above"
    Write-Host "  2. Set OPENCLAW_GATEWAY_TOKEN environment variable"
    Write-Host "  3. Run: .\run-openclaw-upstream.ps1"
    Write-Host ""
    exit 1
}

Write-Host "[OK] All checks passed!" -ForegroundColor Green
Write-Host ""
Write-Host "Ready to start gateway:" -ForegroundColor Green
Write-Host "  .\run-openclaw-upstream.ps1" -ForegroundColor Cyan
Write-Host ""
