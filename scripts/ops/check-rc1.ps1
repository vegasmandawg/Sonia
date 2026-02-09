$ErrorActionPreference = "Stop"
$out = @()
$out += "=== Directory listing of S:\artifacts\phase3 ==="
Get-ChildItem "S:\artifacts\phase3" | ForEach-Object {
    $type = if ($_.PSIsContainer) { "DIR " } else { "FILE" }
    $out += "$type  $($_.Name)"
}
$out += ""
$out += "=== Check rc-1 ==="
if (Test-Path "S:\artifacts\phase3\rc-1") {
    $out += "rc-1 EXISTS"
    $item = Get-Item "S:\artifacts\phase3\rc-1"
    $out += "Type: $($item.GetType().Name)"
    $out += "IsContainer: $($item.PSIsContainer)"
    if ($item.PSIsContainer) {
        Get-ChildItem "S:\artifacts\phase3\rc-1" -Recurse | ForEach-Object {
            $t2 = if ($_.PSIsContainer) { "DIR " } else { "FILE" }
            $out += "  $t2 $($_.FullName)"
        }
    }
} else {
    $out += "rc-1 DOES NOT EXIST"
}
$out | Out-File -FilePath "S:\artifacts\phase3\rc1-check.txt" -Encoding UTF8
Write-Output "DONE"
