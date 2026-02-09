# Build Python 3.10.19 from source on Windows
# Prerequisites: MSVC compiler (Visual Studio) or MinGW

param(
    [string]$SourceFile = "C:\Users\iamth\Downloads\Python-3.10.19.tar.xz",
    [string]$BuildDir = "S:\build\python-310",
    [string]$InstallDir = "S:\tools\python-310"
)

Write-Host ""
Write-Host "================================"
Write-Host "Python 3.10.19 Build Script"
Write-Host "================================"
Write-Host "Timestamp: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
Write-Host ""

# Step 1: Verify source file
Write-Host "[STEP 1] Verifying source file..."
if (-not (Test-Path $SourceFile)) {
    Write-Host "✗ Source file not found: $SourceFile"
    exit 1
}
Write-Host "✓ Found: $SourceFile"
Write-Host "  Size: $(Get-Item $SourceFile | Select-Object -ExpandProperty Length) bytes"
Write-Host ""

# Step 2: Extract TAR.XZ
Write-Host "[STEP 2] Extracting Python source..."
if (Test-Path $BuildDir) {
    Write-Host "Removing existing build directory..."
    Remove-Item $BuildDir -Recurse -Force
}
New-Item -ItemType Directory -Path $BuildDir -Force | Out-Null

Write-Host "Extracting: $SourceFile"
Write-Host "Target: $BuildDir"

# First extract .xz to .tar, then .tar to directory
$tarFile = "$env:TEMP\Python-3.10.19.tar"
Write-Host "Step 2a: Extracting .xz to .tar..."

# Using built-in Windows tar (available in newer Windows versions)
try {
    tar -xf $SourceFile -C $env:TEMP
    if ($LASTEXITCODE -ne 0) {
        Write-Host "✗ TAR extraction failed"
        exit 1
    }
} catch {
    Write-Host "✗ TAR extraction failed: $_"
    Write-Host ""
    Write-Host "Note: Windows 10/11 includes tar command since version 1803"
    Write-Host "If tar is not available, install 7-Zip or use WSL"
    exit 1
}

Write-Host "✓ Extraction complete"
Write-Host ""

# Step 3: Build Python
Write-Host "[STEP 3] Building Python..."
$pythonSourceDir = Get-Item "$env:TEMP\Python-3.10.19" -ErrorAction SilentlyContinue
if (-not $pythonSourceDir) {
    Write-Host "✗ Python source directory not found after extraction"
    Write-Host "Looking in: $env:TEMP"
    Get-ChildItem $env:TEMP -Filter "Python*" -Directory | Select-Object FullName
    exit 1
}

Write-Host "Python source found: $($pythonSourceDir.FullName)"
Write-Host ""

# Check for PCbuild directory (Windows build system)
$pcbuildDir = Join-Path $pythonSourceDir.FullName "PCbuild"
if (-not (Test-Path $pcbuildDir)) {
    Write-Host "✗ PCbuild directory not found"
    Write-Host "  Expected: $pcbuildDir"
    exit 1
}

Write-Host "Build directory: $pcbuildDir"
Write-Host ""

# Try to build with build.bat
$buildBat = Join-Path $pcbuildDir "build.bat"
if (Test-Path $buildBat) {
    Write-Host "Executing: $buildBat Release -d"
    Write-Host ""
    Write-Host "This will take 5-10 minutes..."
    Write-Host ""
    
    Push-Location $pcbuildDir
    & cmd.exe /c "build.bat Release -d"
    $buildExitCode = $LASTEXITCODE
    Pop-Location
    
    if ($buildExitCode -ne 0) {
        Write-Host ""
        Write-Host "✗ Build failed with exit code: $buildExitCode"
        Write-Host ""
        Write-Host "Troubleshooting:"
        Write-Host "1. Ensure Visual Studio 2019 or 2022 is installed"
        Write-Host "2. Run: 'Developer Command Prompt for Visual Studio'"
        Write-Host "3. Navigate to: $pcbuildDir"
        Write-Host "4. Run: build.bat Release -d"
        exit 1
    }
} else {
    Write-Host "✗ build.bat not found at: $buildBat"
    exit 1
}

Write-Host ""
Write-Host "[STEP 4] Verifying build output..."

# After build, python.exe should be in: PCbuild\amd64\python.exe (for Release build)
$pythonExe = Join-Path $pcbuildDir "amd64\python.exe"
if (-not (Test-Path $pythonExe)) {
    Write-Host "✗ python.exe not found at: $pythonExe"
    Write-Host ""
    Write-Host "Build output directory contents:"
    Get-ChildItem $pcbuildDir -Recurse -Filter "python.exe" | Select-Object FullName
    exit 1
}

Write-Host "✓ Python executable built: $pythonExe"
$pythonVersion = & $pythonExe --version 2>&1
Write-Host "  Version: $pythonVersion"
Write-Host ""

# Step 5: Create install directory
Write-Host "[STEP 5] Setting up install directory..."
if (Test-Path $InstallDir) {
    Write-Host "Removing existing install directory..."
    Remove-Item $InstallDir -Recurse -Force
}
New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null
Write-Host "✓ Created: $InstallDir"
Write-Host ""

# Step 6: Copy Python binaries
Write-Host "[STEP 6] Installing Python..."
Write-Host "Copying files from: $pcbuildDir\amd64"
Write-Host "To: $InstallDir"

# Copy all .exe and .dll files from build directory
Copy-Item "$pcbuildDir\amd64\*.exe" $InstallDir -Force
Copy-Item "$pcbuildDir\amd64\*.dll" $InstallDir -Force
Copy-Item "$pcbuildDir\amd64\*.pyd" $InstallDir -Force -ErrorAction SilentlyContinue

Write-Host "✓ Binaries copied"
Write-Host ""

# Step 7: Verify installation
Write-Host "[STEP 7] Verifying installation..."
$installedPython = Join-Path $InstallDir "python.exe"
if (-not (Test-Path $installedPython)) {
    Write-Host "✗ Installation verification failed"
    exit 1
}

$version = & $installedPython --version 2>&1
Write-Host "✓ Python installed successfully"
Write-Host "  Path: $installedPython"
Write-Host "  Version: $version"
Write-Host ""

Write-Host "================================"
Write-Host "Build Complete"
Write-Host "================================"
Write-Host "Python 3.10 is ready at: $InstallDir"
Write-Host ""
Write-Host "Next step: Execute Gate 1 with this Python installation"
Write-Host ""

exit 0
