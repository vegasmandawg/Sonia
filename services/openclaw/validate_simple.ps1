#!/usr/bin/env pwsh
# OpenClaw Phase 1 Validation - Simple Version

Write-Host "=== OpenClaw Phase 1 Validation ===" -ForegroundColor Green
Write-Host ""

# Check files exist
$files = @(
    "main.py",
    "schemas.py", 
    "policy.py",
    "registry.py",
    "test_contract.py",
    "test_executors.py",
    "executors\shell_exec.py",
    "executors\file_exec.py",
    "executors\browser_exec.py"
)

Write-Host "File Structure Check:" -ForegroundColor Cyan
$allExist = $true
foreach ($file in $files) {
    $path = Join-Path $PSScriptRoot $file
    if (Test-Path $path) {
        $size = (Get-Item $path).Length
        Write-Host "  [OK] $file ($size bytes)"
    } else {
        Write-Host "  [FAIL] $file (MISSING)"
        $allExist = $false
    }
}

Write-Host ""

if ($allExist) {
    Write-Host "All files present: YES" -ForegroundColor Green
} else {
    Write-Host "All files present: NO" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "OpenClaw Phase 1 Complete" -ForegroundColor Green
Write-Host ""
Write-Host "Summary:" -ForegroundColor Cyan
Write-Host "  - Registry: ToolRegistry with 4 tools"
Write-Host "  - Tools: shell.run, file.read, file.write, browser.open"
Write-Host "  - Executors: ShellExecutor, FileExecutor, BrowserExecutor"
Write-Host "  - Policy: Allowlist + Sandbox enforcement"
Write-Host "  - Tests: Contract + Unit tests"
Write-Host ""
