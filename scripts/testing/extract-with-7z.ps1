# Extract Python 3.10.19 using 7-Zip
param(
    [string]$SourceFile = "C:\Users\iamth\Downloads\Python-3.10.19.tar.xz"
)

Write-Host "Looking for 7-Zip installation..."

# Common 7-Zip installation paths
$sevenZipPaths = @(
    "C:\Program Files\7-Zip\7z.exe",
    "C:\Program Files (x86)\7-Zip\7z.exe",
    "C:\Program Files\Git\usr\bin\tar.exe",
    "C:\tools\7z\7z.exe"
)

$sevenZip = $null
foreach ($path in $sevenZipPaths) {
    if (Test-Path $path) {
        $sevenZip = $path
        Write-Host "Found 7-Zip at: $path"
        break
    }
}

if (-not $sevenZip) {
    Write-Host "7-Zip not found at standard locations"
    Write-Host ""
    Write-Host "Searching system..."
    
    $found = Get-Command 7z -ErrorAction SilentlyContinue
    if ($found) {
        $sevenZip = $found.Source
        Write-Host "Found 7z command at: $sevenZip"
    }
}

if (-not $sevenZip) {
    Write-Host "ERROR: 7-Zip not found"
    Write-Host ""
    Write-Host "Solutions:"
    Write-Host "1. Install 7-Zip from: https://www.7-zip.org/"
    Write-Host "2. Or install with: choco install 7zip"
    Write-Host "3. Or use WSL: wsl tar -xf file.tar.xz"
    exit 1
}

Write-Host ""
Write-Host "Using: $sevenZip"
Write-Host "Extracting: $SourceFile"

# 7z can extract .tar.xz directly
$extractDir = "C:\temp\python-src"
if (Test-Path $extractDir) {
    Remove-Item $extractDir -Recurse -Force
}
New-Item -ItemType Directory -Path $extractDir -Force | Out-Null

& $sevenZip x $SourceFile -o"$extractDir"

$exitCode = $LASTEXITCODE
if ($exitCode -eq 0) {
    Write-Host "SUCCESS"
    Get-ChildItem $extractDir | Select-Object Name
} else {
    Write-Host "FAILED with exit code: $exitCode"
}

exit $exitCode
