# Install Miniconda3 from fresh copy in Downloads
param(
    [string]$InstallerPath = "C:\Users\iamth\Downloads\Miniconda3-py311_25.11.1-1-Windows-x86_64 (1).exe",
    [string]$InstallDir = "S:\tools\python"
)

Write-Host ""
Write-Host "=========================================="
Write-Host "Installing Miniconda3 (Fresh Copy)"
Write-Host "=========================================="
Write-Host "Timestamp: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss.fff')"
Write-Host ""

# Verify installer exists
if (-not (Test-Path $InstallerPath)) {
    Write-Host "ERROR: Installer not found"
    Write-Host "Path: $InstallerPath"
    exit 1
}

Write-Host "Found installer: $InstallerPath"
$installerSize = (Get-Item $InstallerPath).Length
Write-Host "Size: $([Math]::Round($installerSize / 1MB, 2)) MB"
Write-Host ""

# Remove any previous partial installation
if (Test-Path $InstallDir) {
    Write-Host "Removing previous installation attempt..."
    Remove-Item $InstallDir -Recurse -Force -ErrorAction SilentlyContinue
}

Write-Host "Installation directory: $InstallDir"
Write-Host ""

# Execute installer with same flags as before, but this is a fresh copy
Write-Host "Executing installer..."
Write-Host "  /InstallationType=JustMe"
Write-Host "  /RegisterPython=1"
Write-Host "  /S (silent)"
Write-Host "  /D=$InstallDir"
Write-Host ""

& $InstallerPath /InstallationType=JustMe /RegisterPython=1 /S /D=$InstallDir

$installExitCode = $LASTEXITCODE
Write-Host "Installer exit code: $installExitCode"
Write-Host ""

# Wait for any background processes
Write-Host "Waiting for installation to complete..."
Start-Sleep -Seconds 5

Write-Host "Verifying installation..."
$pythonExe = Join-Path $InstallDir "python.exe"

if (Test-Path $pythonExe) {
    Write-Host "SUCCESS: Python executable found"
    $version = & $pythonExe --version 2>&1
    Write-Host "Version: $version"
    Write-Host ""
    Write-Host "Ready to execute Gate 1"
    exit 0
} else {
    Write-Host "VERIFICATION FAILED: python.exe not found"
    Write-Host "Expected path: $pythonExe"
    Write-Host ""
    Write-Host "Directory contents:"
    if (Test-Path $InstallDir) {
        Get-ChildItem $InstallDir | Select-Object Name, Length | Format-Table
    }
    exit 1
}
