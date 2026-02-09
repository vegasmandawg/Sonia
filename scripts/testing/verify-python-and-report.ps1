# Quick verification of Python installation status

$pythonPath = "S:\tools\python\python.exe"
$timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss.fff"

Write-Host "[$timestamp] Python Installation Status Check"
Write-Host ""

if (Test-Path $pythonPath) {
    Write-Host "✓ PYTHON FOUND at: $pythonPath"
    
    $version = & $pythonPath --version 2>&1
    $exitCode = $LASTEXITCODE
    
    if ($exitCode -eq 0) {
        Write-Host "✓ PYTHON WORKING: $version"
        Write-Host ""
        Write-Host "Ready to execute Gate 1"
        exit 0
    } else {
        Write-Host "✗ Python found but failed: $version (exit: $exitCode)"
        exit 1
    }
} else {
    Write-Host "⏳ Python not yet available"
    Write-Host ""
    
    # Check directory status
    if (Test-Path "S:\tools\python") {
        $dirInfo = Get-Item "S:\tools\python"
        Write-Host "Directory: S:\tools\python"
        Write-Host "  Last Modified: $($dirInfo.LastWriteTime)"
        Write-Host "  Subdirs: $(Get-ChildItem 'S:\tools\python' -Directory -ErrorAction SilentlyContinue | Measure-Object | Select-Object -ExpandProperty Count)"
        Write-Host ""
        Write-Host "Installation still in progress..."
        exit 2
    } else {
        Write-Host "✗ Directory S:\tools\python does not exist"
        exit 1
    }
}
