# Direct Python 3.11 installation from python.org

Write-Host "Attempting direct Python 3.11.9 installation..."
Write-Host ""

$pythonVersion = "3.11.9"
$downloadUrl = "https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe"
$installerPath = "$env:TEMP\python-3.11.9-amd64.exe"
$pythonInstallDir = "S:\tools\python-311"

Write-Host "Download URL: $downloadUrl"
Write-Host "Installer Path: $installerPath"
Write-Host "Install Dir: $pythonInstallDir"
Write-Host ""

# Check if already installed
if (Test-Path "$pythonInstallDir\python.exe") {
    Write-Host "✓ Python already installed"
    & "$pythonInstallDir\python.exe" --version
    exit 0
}

Write-Host "Downloading Python 3.11.9..."
try {
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    Invoke-WebRequest -Uri $downloadUrl -OutFile $installerPath -ErrorAction Stop
    Write-Host "✓ Download complete"
} catch {
    Write-Host "✗ Download failed: $_"
    exit 1
}

Write-Host ""
Write-Host "Installing Python..."
Write-Host "  Arguments: /quiet InstallAllUsers=0 PrependPath=0 TargetPath=$pythonInstallDir"

& $installerPath /quiet InstallAllUsers=0 PrependPath=0 TargetPath=$pythonInstallDir

Start-Sleep -Seconds 3

if (Test-Path "$pythonInstallDir\python.exe") {
    Write-Host "✓ Installation successful"
    & "$pythonInstallDir\python.exe" --version
    exit 0
} else {
    Write-Host "✗ Installation failed"
    exit 1
}
