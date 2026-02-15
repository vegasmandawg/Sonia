# Diagnostic: Check if Gate 1 prerequisites exist

Write-Host "Gate 1 Diagnostic Check"
Write-Host "======================"
Write-Host ""

# Check start-sonia-stack.ps1
Write-Host "1. Checking start-sonia-stack.ps1..."
$startScript = "S:\start-sonia-stack.ps1"
if (Test-Path $startScript) {
    Write-Host "   [OK] Found: $startScript"
} else {
    Write-Host "   [FAIL] NOT FOUND: $startScript"
}

Write-Host ""
Write-Host "2. Checking stop-sonia-stack.ps1..."
$stopScript = "S:\stop-sonia-stack.ps1"
if (Test-Path $stopScript) {
    Write-Host "   [OK] Found: $stopScript"
} else {
    Write-Host "   [FAIL] NOT FOUND: $stopScript"
}

Write-Host ""
Write-Host "3. Checking service run scripts..."
$serviceScripts = @(
    "S:\scripts\ops\run-api-gateway.ps1",
    "S:\scripts\ops\run-model-router.ps1",
    "S:\scripts\ops\run-memory-engine.ps1",
    "S:\scripts\ops\run-pipecat.ps1",
    "S:\scripts\ops\run-openclaw.ps1",
    "S:\scripts\ops\run-eva-os.ps1"
)

foreach ($script in $serviceScripts) {
    $name = Split-Path $script -Leaf
    if (Test-Path $script) {
        Write-Host "   [OK] $name"
    } else {
        Write-Host "   [FAIL] $name (NOT FOUND)"
    }
}

Write-Host ""
Write-Host "4. Checking directories..."
$dirs = @(
    "S:\state\pids",
    "S:\logs\services",
    "S:\artifacts\phase3",
    "S:\artifacts\phase3\gate-results",
    "S:\artifacts\phase3\manifests"
)

foreach ($dir in $dirs) {
    if (Test-Path $dir) {
        Write-Host "   [OK] $dir"
    } else {
        Write-Host "   [FAIL] $dir (creating...)"
        New-Item -ItemType Directory -Path $dir -Force | Out-Null
        Write-Host "     Created"
    }
}

Write-Host ""
Write-Host "5. Checking integration test path..."
$testPath = "S:\tests\integration\test_phase2_e2e.py"
if (Test-Path $testPath) {
    Write-Host "   [OK] Found: $testPath"
} else {
    Write-Host "   [FAIL] NOT FOUND: $testPath"
}

Write-Host ""
Write-Host "6. Python verification..."
$python = "S:\tools\python\python.exe"
if (Test-Path $python) {
    Write-Host "   [OK] Python found"
    & $python --version
} else {
    Write-Host "   [FAIL] Python NOT found"
}

Write-Host ""
Write-Host "Summary: Check what's missing and ensure all prerequisites exist"
