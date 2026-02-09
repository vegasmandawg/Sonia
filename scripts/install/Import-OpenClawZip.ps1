<#---------------------------------------------------------------------------
Import-OpenClawZip.ps1
Vends an upstream OpenClaw source ZIP into the Sonia canonical root (S:\).

Behavior:
- Resolves ZipPath robustly (supports "\Downloads\..." style inputs)
- Computes SHA256
- Copies ZIP into:   S:\integrations\openclaw\upstream\archives\
- Extracts into:     S:\integrations\openclaw\upstream\src\<project>_<hashprefix>[_<timestamp>]\
- Writes:
    S:\integrations\openclaw\upstream\CURRENT.txt   (points to extracted root)
    S:\integrations\openclaw\upstream\imports.jsonl (append-only import records)

Idempotent:
- If the same SHA256 has already been imported and extract_path exists, it will
  NOT re-extract (unless -ForceExtract). It will repoint CURRENT.txt.

Usage:
  powershell -ExecutionPolicy Bypass -File S:\scripts\install\Import-OpenClawZip.ps1 -ZipPath "\Downloads\openclaw-main.zip"
  powershell -ExecutionPolicy Bypass -File S:\scripts\install\Import-OpenClawZip.ps1 -ZipPath "C:\Users\you\Downloads\openclaw-main.zip" -ForceExtract
---------------------------------------------------------------------------#>

[CmdletBinding()]
param(
    [Parameter(Mandatory = $false)]
    [ValidateNotNullOrEmpty()]
    [string]$Root = "S:\",

    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$ZipPath,

    [Parameter(Mandatory = $false)]
    [ValidateNotNullOrEmpty()]
    [string]$ProjectName = "openclaw",

    [Parameter(Mandatory = $false)]
    [switch]$ForceExtract
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Ensure-Dir {
    param([Parameter(Mandatory = $true)][string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) {
        New-Item -ItemType Directory -Path $Path -Force | Out-Null
    }
}

function Normalize-Root {
    param([Parameter(Mandatory = $true)][string]$Path)
    if (-not $Path.EndsWith("\")) { return "$Path\" }
    return $Path
}

function Resolve-ZipPath {
    param([Parameter(Mandatory = $true)][string]$InputPath)

    # Already absolute (drive-qualified or UNC)
    if ($InputPath -match "^[a-zA-Z]:\\") { return $InputPath }
    if ($InputPath -match "^\\\\") { return $InputPath }

    $candidate = $null

    # "\Downloads\file.zip" => "C:\Downloads\file.zip" (or whatever HOMEDRIVE is)
    if ($InputPath.StartsWith("\")) {
        $candidate = "$($env:HOMEDRIVE)$InputPath"
        if (Test-Path -LiteralPath $candidate) { return $candidate }
    }

    # Relative to current directory
    $rel = Resolve-Path -LiteralPath $InputPath -ErrorAction SilentlyContinue
    if ($rel) { return $rel.Path }

    # Fallback: %USERPROFILE%\Downloads\<leaf>
    $leaf = Split-Path -Leaf $InputPath
    $dl = Join-Path $env:USERPROFILE "Downloads\$leaf"
    if (Test-Path -LiteralPath $dl) { return $dl }

    $candText = if ($candidate) { $candidate } else { "(none)" }
    throw "ZIP not found. Provided: '$InputPath'. Tried: '$candText' and '$dl'."
}

$Root = Normalize-Root -Path $Root
$driveLetter = $Root.Substring(0,1)
if (-not (Get-PSDrive -Name $driveLetter -ErrorAction SilentlyContinue)) {
    throw "Drive '$($driveLetter):' does not exist. Update -Root first."
}

$ResolvedZip = Resolve-ZipPath -InputPath $ZipPath
if (-not (Test-Path -LiteralPath $ResolvedZip)) {
    throw "ZIP not found at: $ResolvedZip"
}

# Sonia vendor locations
$BaseDir     = Join-Path $Root "integrations\$ProjectName\upstream"
$ArchivesDir = Join-Path $BaseDir "archives"
$SrcDir      = Join-Path $BaseDir "src"
$IndexFile   = Join-Path $BaseDir "imports.jsonl"
$CurrentFile = Join-Path $BaseDir "CURRENT.txt"

Ensure-Dir -Path $BaseDir
Ensure-Dir -Path $ArchivesDir
Ensure-Dir -Path $SrcDir

# Hash the ZIP
$zipHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $ResolvedZip).Hash
$hashPrefix = $zipHash.Substring(0,12)
$stamp = Get-Date -Format "yyyyMMdd_HHmmss"

# Reuse prior import if present (unless forced)
$existingDest = $null
if (Test-Path -LiteralPath $IndexFile) {
    $lines = Get-Content -LiteralPath $IndexFile -ErrorAction SilentlyContinue
    foreach ($ln in $lines) {
        if ([string]::IsNullOrWhiteSpace($ln)) { continue }
        try {
            $obj = $ln | ConvertFrom-Json -ErrorAction Stop
            if ($obj.sha256 -eq $zipHash) {
                $p = [string]$obj.extract_path
                if ($p -and (Test-Path -LiteralPath $p)) {
                    $existingDest = $p
                    break
                }
            }
        } catch {
            # ignore malformed lines
        }
    }
}

if ($existingDest -and -not $ForceExtract) {
    Set-Content -LiteralPath $CurrentFile -Value $existingDest -Encoding UTF8
    Write-Host ""
    Write-Host "Already imported (SHA256 match)."
    Write-Host "CURRENT -> $existingDest"
    exit 0
}

# Copy ZIP into archives (keeps provenance under S:\)
$zipLeaf = Split-Path -Leaf $ResolvedZip
$archiveName = "{0}_{1}_{2}" -f $ProjectName, $hashPrefix, $zipLeaf
$ArchivedZip = Join-Path $ArchivesDir $archiveName
Copy-Item -LiteralPath $ResolvedZip -Destination $ArchivedZip -Force

# Extract into a versioned folder (non-destructive)
$ExtractBase = Join-Path $SrcDir ("{0}_{1}" -f $ProjectName, $hashPrefix)
if (Test-Path -LiteralPath $ExtractBase) {
    $ExtractBase = Join-Path $SrcDir ("{0}_{1}_{2}" -f $ProjectName, $hashPrefix, $stamp)
}
Ensure-Dir -Path $ExtractBase

Write-Host ""
Write-Host "Importing OpenClaw ZIP into Sonia root..."
Write-Host "ZIP:      $ResolvedZip"
Write-Host "SHA256:   $zipHash"
Write-Host "Archive:  $ArchivedZip"
Write-Host "Extract:  $ExtractBase"

Expand-Archive -LiteralPath $ArchivedZip -DestinationPath $ExtractBase -Force

# If archive expands into a single top-level folder, point CURRENT there.
$children = @(Get-ChildItem -LiteralPath $ExtractBase -Force -ErrorAction SilentlyContinue)
$target = $ExtractBase
if ($children.Count -eq 1 -and $children[0].PSIsContainer) {
    $target = $children[0].FullName
}

Set-Content -LiteralPath $CurrentFile -Value $target -Encoding UTF8

# Append import record
$record = [ordered]@{
    timestamp    = (Get-Date).ToString("s")
    project      = $ProjectName
    source_zip   = $ResolvedZip
    archived_zip = $ArchivedZip
    sha256       = $zipHash
    extract_path = $target
}
($record | ConvertTo-Json -Compress) + "`r`n" | Out-File -LiteralPath $IndexFile -Encoding UTF8 -Append

Write-Host ""
Write-Host "Done."
Write-Host "CURRENT -> $target"
Write-Host "Index   -> $IndexFile"
