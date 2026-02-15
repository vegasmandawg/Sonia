$ErrorActionPreference = "Stop"
$rel = "S:\releases\v3.1.0-rc1"
$sumsFile = "$rel\SHA256SUMS.txt"

if (-not (Test-Path $sumsFile)) {
    Write-Host "ERROR: SHA256SUMS.txt not found at $sumsFile"
    exit 1
}

$lines = Get-Content $sumsFile -Encoding utf8 | Where-Object { $_.Trim() -ne "" }
$total = 0
$matched = 0
$mismatched = 0

foreach ($line in $lines) {
    $parts = $line -split "  ", 2
    if ($parts.Count -ne 2) { continue }
    $expectedHash = $parts[0].Trim()
    $filePath = $parts[1].Trim()

    $total++
    if (-not (Test-Path $filePath)) {
        Write-Host "MISSING: $filePath"
        $mismatched++
        continue
    }

    $actual = (Get-FileHash -Path $filePath -Algorithm SHA256).Hash
    if ($actual -eq $expectedHash) {
        Write-Host "OK: $(Split-Path $filePath -Leaf)"
        $matched++
    } else {
        Write-Host "MISMATCH: $(Split-Path $filePath -Leaf)"
        Write-Host "  Expected: $expectedHash"
        Write-Host "  Actual:   $actual"
        $mismatched++
    }
}

Write-Host ""
Write-Host "Verified: $matched/$total matched, $mismatched mismatched"
if ($mismatched -eq 0) {
    Write-Host "VERDICT: PASS"
    exit 0
} else {
    Write-Host "VERDICT: FAIL"
    exit 1
}
