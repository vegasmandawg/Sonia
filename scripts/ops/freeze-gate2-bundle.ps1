Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$bundle = "S:\artifacts\phase3\gate-results\gate2-$stamp"
New-Item -ItemType Directory -Path $bundle -Force | Out-Null

# Copy the latest go-no-go log and summary
$latestLog = Get-ChildItem "S:\artifacts\phase3\go-no-go-*.log" | Sort-Object LastWriteTime -Descending | Select-Object -First 1
$latestJson = Get-ChildItem "S:\artifacts\phase3\go-no-go-summary-*.json" -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 1

if ($latestLog) { Copy-Item $latestLog.FullName $bundle -Force }
if ($latestJson) { Copy-Item $latestJson.FullName $bundle -Force }

$files = @(Get-ChildItem $bundle -File)
if ($files.Count -eq 0) {
    Write-Host "[WARN] No artifact files found to bundle." -ForegroundColor Yellow
} else {
    $files | Get-FileHash -Algorithm SHA256 | Sort-Object Path |
        Export-Csv "$bundle\SHA256SUMS.csv" -NoTypeInformation
    Write-Host "[OK] Gate 2 evidence bundle frozen at: $bundle" -ForegroundColor Green
    Write-Host "     Files: $($files.Count)" -ForegroundColor Cyan
    Get-ChildItem $bundle -File | ForEach-Object { Write-Host "       $($_.Name)  ($($_.Length) bytes)" }
}
