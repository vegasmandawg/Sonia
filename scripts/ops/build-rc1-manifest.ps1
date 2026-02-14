Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$rcDir = "S:\artifacts\phase3\rc-1"
if (Test-Path $rcDir) {
    Remove-Item $rcDir -Recurse -Force
}
New-Item -ItemType Directory -Path $rcDir -Force | Out-Null

Write-Host "`n=== BUILDING RC-1 MANIFEST ===" -ForegroundColor Cyan

# 1. Copy BOOT_CONTRACT.md
Copy-Item "S:\artifacts\phase3\BOOT_CONTRACT.md" $rcDir -Force
Write-Host "[OK] BOOT_CONTRACT.md" -ForegroundColor Green

# 2. Copy gate-status.json
Copy-Item "S:\artifacts\phase3\gate-status.json" $rcDir -Force
Write-Host "[OK] gate-status.json" -ForegroundColor Green

# 3. Copy the canonical go-no-go log + summary from the passing run
Copy-Item "S:\artifacts\phase3\go-no-go-20260208_164811.log" $rcDir -Force
Copy-Item "S:\artifacts\phase3\go-no-go-summary-20260208_164811.json" $rcDir -Force
Write-Host "[OK] go-no-go log + summary" -ForegroundColor Green

# 4. Copy all 4 gate evidence bundles (from the freeze stamp)
$freezeStamp = "20260208-172235"
$gateNames = @("gate1", "gate2", "gate2b", "gate3")
foreach ($gate in $gateNames) {
    $srcDir = "S:\artifacts\phase3\gate-results\$gate-$freezeStamp"
    if (Test-Path $srcDir) {
        $destDir = Join-Path $rcDir "evidence\$gate"
        Copy-Item $srcDir $destDir -Recurse -Force
        $fileCount = @(Get-ChildItem $destDir -File -Recurse).Count
        Write-Host "[OK] evidence\$gate ($fileCount files)" -ForegroundColor Green
    } else {
        Write-Host "[WARN] Missing: $srcDir" -ForegroundColor Yellow
    }
}

# 5. Copy the release artifact bundle (Gate 3 output)
$bundleSrc = "S:\artifacts\phase3\bundle-20260208_164811"
if (Test-Path $bundleSrc) {
    $bundleDest = Join-Path $rcDir "release-bundle"
    Copy-Item $bundleSrc $bundleDest -Recurse -Force
    $fileCount = @(Get-ChildItem $bundleDest -File -Recurse).Count
    Write-Host "[OK] release-bundle ($fileCount files)" -ForegroundColor Green
}

# 6. Copy the go-no-go script itself (the version that produced the results)
Copy-Item "S:\scripts\testing\phase3-go-no-go.ps1" $rcDir -Force
Write-Host "[OK] phase3-go-no-go.ps1 (script snapshot)" -ForegroundColor Green

# 7. Generate top-level SHA256 manifest of everything
Write-Host "`nGenerating SHA256 manifest..." -ForegroundColor Cyan
$allFiles = @(Get-ChildItem $rcDir -File -Recurse)
$manifest = $allFiles | Get-FileHash -Algorithm SHA256 | Sort-Object Path | ForEach-Object {
    @{
        Algorithm = $_.Algorithm
        Hash = $_.Hash
        RelativePath = $_.Path.Replace("$rcDir\", "")
    }
}

$manifestJson = @{
    generated = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
    rc_version = "RC-1"
    total_files = $allFiles.Count
    files = $manifest
} | ConvertTo-Json -Depth 4

$manifestJson | Out-File -FilePath (Join-Path $rcDir "MANIFEST.json") -Encoding UTF8

# Also generate a simple text manifest
$allFiles | Get-FileHash -Algorithm SHA256 | Sort-Object Path | ForEach-Object {
    $relativePath = $_.Path.Replace("${rcDir}\", "")
    "$($_.Hash)  $relativePath"
} | Out-File -FilePath (Join-Path $rcDir "SHA256SUMS.txt") -Encoding UTF8

Write-Host "[OK] MANIFEST.json ($($allFiles.Count) files hashed)" -ForegroundColor Green
Write-Host "[OK] SHA256SUMS.txt" -ForegroundColor Green

Write-Host "`n=== RC-1 MANIFEST COMPLETE ===" -ForegroundColor Cyan
Write-Host "Location: $rcDir" -ForegroundColor White
Write-Host "Files: $($allFiles.Count + 2)" -ForegroundColor White
