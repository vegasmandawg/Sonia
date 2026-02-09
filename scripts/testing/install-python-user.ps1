# Install Python to a user-writable location (S:\tools\python)
# This avoids permission issues with C:\Program Files

param(
    [switch]$UseElevation
)

$pythonInstallDir = "S:\tools\python"

Write-Host "Checking for Python installation..."

# Check if Python already exists
if (Test-Path "$pythonInstallDir\python.exe") {
    Write-Host "✓ Python already installed at $pythonInstallDir"
    & "$pythonInstallDir\python.exe" --version
    exit 0
}

# Try Miniconda first (more lightweight)
Write-Host "Installing Miniconda3 to $pythonInstallDir..."

$installerPath = "S:\tools\sysprog\Miniconda3-py311_25.11.1-1-Windows-x86_64.exe"

if (-not (Test-Path $installerPath)) {
    Write-Host "✗ Miniconda3 installer not found at $installerPath"
    exit 1
}

# Create the installation directory
if (-not (Test-Path $pythonInstallDir)) {
    New-Item -ItemType Directory -Path $pythonInstallDir -Force | Out-Null
}

Write-Host "Executing Miniconda3 installer..."
Write-Host "  Installer: $installerPath"
Write-Host "  Target: $pythonInstallDir"
Write-Host "  Mode: /InstallationType=JustMe /RegisterPython=0 /AddToPath=0"
Write-Host ""

$installArgs = @(
    "/InstallationType=JustMe"
    "/RegisterPython=0"
    "/AddToPath=0"
    "/S"
    "/D=$pythonInstallDir"
)

& $installerPath $installArgs

Start-Sleep -Seconds 3

# Verify installation
if (Test-Path "$pythonInstallDir\python.exe") {
    Write-Host ""
    Write-Host "✓ Python installation succeeded at $pythonInstallDir"
    & "$pythonInstallDir\python.exe" --version
    
    Write-Host ""
    Write-Host "To use this Python:"
    Write-Host "  Full path: $pythonInstallDir\python.exe"
    Write-Host "  In scripts: & '$pythonInstallDir\python.exe' --version"
    Write-Host ""
    
    exit 0
} else {
    Write-Host ""
    Write-Host "✗ Installation failed - python.exe not found at $pythonInstallDir"
    Write-Host ""
    Write-Host "Checking installation directory contents:"
    if (Test-Path $pythonInstallDir) {
        Get-ChildItem $pythonInstallDir -Recurse -Depth 2
    }
    exit 1
}
