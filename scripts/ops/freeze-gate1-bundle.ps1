Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$bundle = "S:\artifacts\phase3\gate-results\gate1-$stamp"
New-Item -ItemType Directory -Path $bundle -Force | Out-Null

Copy-Item "S:\artifacts\phase3\go-no-go-summary-*.json" $bundle -Force -ErrorAction SilentlyContinue
Copy-Item "S:\artifacts\phase3\go-no-go-*.log" $bundle -Force -ErrorAction SilentlyContinue
Copy-Item "S:\artifacts\phase3\test-gate1-*.txt" $bundle -Force -ErrorAction SilentlyContinue

$files = Get-ChildItem $bundle -File
if ($files.Count -eq 0) {
    Write-Host "[WARN] No artifact files found to bundle." -ForegroundColor Yellow
} else {
    $files | Get-FileHash -Algorithm SHA256 | Sort-Object Path |
        Export-Csv "$bundle\SHA256SUMS.csv" -NoTypeInformation
    Write-Host "[OK] Gate 1 evidence bundle frozen at: $bundle" -ForegroundColor Green
    Write-Host "     Files: $($files.Count)" -ForegroundColor Cyan
    Get-ChildItem $bundle -File | ForEach-Object { Write-Host "       $($_.Name)  ($($_.Length) bytes)" }
}
