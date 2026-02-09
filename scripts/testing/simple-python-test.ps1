# Simple Python test
$pythonExe = "S:\tools\python\python.exe"

Write-Host "Testing Python..."
Write-Host "Path: $pythonExe"
Write-Host ""

& $pythonExe -c "import sys; print('Python ' + sys.version); print('Hash Seed: ' + str(__import__('os').environ.get('PYTHONHASHSEED', 'not set')))"

if ($LASTEXITCODE -eq 0) {
    Write-Host ""
    Write-Host "SUCCESS: Python is working!"
    exit 0
} else {
    Write-Host ""
    Write-Host "FAILED: Python test exited with code $($LASTEXITCODE)"
    exit 1
}
