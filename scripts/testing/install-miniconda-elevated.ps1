# Install Miniconda3 with elevated privileges
# This script checks if it's running as admin and installs Miniconda3

# Check if running as admin
$isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole] "Administrator")

if (-not $isAdmin) {
    Write-Host "This script requires elevated privileges (Administrator)."
    Write-Host "Requesting elevation..."
    
    # Re-run this script as admin
    $scriptPath = $MyInvocation.MyCommand.Path
    Start-Process -FilePath "powershell.exe" `
        -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$scriptPath`"" `
        -Verb RunAs `
        -Wait
    exit 0
}

Write-Host "Running as Administrator."
Write-Host ""

$installerPath = "S:\tools\sysprog\Miniconda3-py311_25.11.1-1-Windows-x86_64.exe"
$installDir = "C:\Miniconda3"

Write-Host "Checking Miniconda3 installation..."
if (Test-Path "$installDir\python.exe") {
    Write-Host "✓ Miniconda3 is already installed at $installDir"
    & "$installDir\python.exe" --version
    exit 0
}

Write-Host "Miniconda3 not found. Installing from: $installerPath"

if (-not (Test-Path $installerPath)) {
    Write-Host "✗ Installer not found: $installerPath"
    exit 1
}

Write-Host "Executing Miniconda3 installer..."
Write-Host "  /InstallationType=JustMe"
Write-Host "  /RegisterPython=1"
Write-Host "  /S (silent)"
Write-Host "  /D=$installDir"
Write-Host ""

& $installerPath /InstallationType=JustMe /RegisterPython=1 /S /D=$installDir

# Wait for installer to complete
Start-Sleep -Seconds 5

# Verify installation
if (Test-Path "$installDir\python.exe") {
    Write-Host "✓ Miniconda3 installation succeeded!"
    & "$installDir\python.exe" --version
    
    # Refresh PATH
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
    Write-Host ""
    Write-Host "✓ Python is ready for use"
    exit 0
} else {
    Write-Host "✗ Miniconda3 installation failed - python.exe not found at $installDir"
    exit 1
}
