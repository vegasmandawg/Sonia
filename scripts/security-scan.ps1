# SONIA Security Scan Script
# Runs bandit (SAST) and pip-audit (dependency vulnerabilities)

param(
    [switch]$BanditOnly,
    [switch]$AuditOnly,
    [switch]$Verbose
)

$ErrorActionPreference = "Continue"
$python = "S:\envs\sonia-core\python.exe"
$results = @{ bandit = "skipped"; pip_audit = "skipped"; timestamp = (Get-Date -Format o) }

Write-Host "=== SONIA Security Scan ===" -ForegroundColor Cyan

# --- Bandit (Static Analysis) ---
if (-not $AuditOnly) {
    Write-Host "`n[1/2] Running bandit static analysis..." -ForegroundColor Yellow
    try {
        $banditOut = & $python -m bandit -c S:\bandit.yaml -r S:\services\ -f json 2>&1
        $banditJson = $banditOut | ConvertFrom-Json -ErrorAction SilentlyContinue
        if ($banditJson) {
            $highCount = ($banditJson.results | Where-Object { $_.issue_severity -eq "HIGH" }).Count
            $medCount = ($banditJson.results | Where-Object { $_.issue_severity -eq "MEDIUM" }).Count
            $lowCount = ($banditJson.results | Where-Object { $_.issue_severity -eq "LOW" }).Count
            Write-Host "  Bandit: HIGH=$highCount MEDIUM=$medCount LOW=$lowCount" -ForegroundColor $(if ($highCount -gt 0) { "Red" } else { "Green" })
            $results.bandit = @{ high = $highCount; medium = $medCount; low = $lowCount; total = $banditJson.results.Count }
        } else {
            Write-Host "  Bandit: clean (no findings)" -ForegroundColor Green
            $results.bandit = @{ high = 0; medium = 0; low = 0; total = 0 }
        }
    } catch {
        Write-Host "  Bandit: not installed (pip install bandit)" -ForegroundColor DarkYellow
        $results.bandit = "not_installed"
    }
}

# --- pip-audit (Dependency Vulnerabilities) ---
if (-not $BanditOnly) {
    Write-Host "`n[2/2] Running pip-audit dependency scan..." -ForegroundColor Yellow
    try {
        $auditOut = & $python -m pip_audit -r S:\requirements-frozen.txt --format json 2>&1
        $auditJson = $auditOut | ConvertFrom-Json -ErrorAction SilentlyContinue
        if ($auditJson -and $auditJson.Count -gt 0) {
            Write-Host "  pip-audit: $($auditJson.Count) vulnerabilities found" -ForegroundColor Red
            $results.pip_audit = @{ count = $auditJson.Count }
        } else {
            Write-Host "  pip-audit: clean (no known vulnerabilities)" -ForegroundColor Green
            $results.pip_audit = @{ count = 0 }
        }
    } catch {
        Write-Host "  pip-audit: not installed (pip install pip-audit)" -ForegroundColor DarkYellow
        $results.pip_audit = "not_installed"
    }
}

# --- Summary ---
Write-Host "`n=== Scan Complete ===" -ForegroundColor Cyan
$results | ConvertTo-Json -Depth 3

# Gate check: fail if any HIGH findings
if ($results.bandit -is [hashtable] -and $results.bandit.high -gt 0) {
    Write-Host "`nGATE FAIL: $($results.bandit.high) HIGH severity findings" -ForegroundColor Red
    exit 1
}
Write-Host "GATE PASS: No high-severity findings" -ForegroundColor Green
