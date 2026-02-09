$ErrorActionPreference = "Stop"
$rcDir = "S:\artifacts\phase3\rc-1"

$allFiles = @(Get-ChildItem $rcDir -File -Recurse | Where-Object { $_.Name -ne "SHA256SUMS.txt" })
$hashLines = @()
foreach ($f in $allFiles) {
    $hash = (Get-FileHash -LiteralPath $f.FullName -Algorithm SHA256).Hash
    $rel = $f.FullName.Replace("$rcDir\", "")
    $hashLines += "$hash  $rel"
}
$hashLines | Out-File -FilePath "$rcDir\SHA256SUMS.txt" -Encoding UTF8

"Rehashed $($allFiles.Count) files (excluding SHA256SUMS.txt itself)" | Out-File -FilePath "S:\artifacts\phase3\rehash-log.txt" -Encoding UTF8
